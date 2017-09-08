# -*- coding: utf-8 -*-
#
# Retrieve Nest Developer API information on thermostats
# save the status of the thermostats and send push notifications
# via IFTTT based on previous state not matching current state. 
#
# Uses SQLite for datastore
#
# Pat O'Brien - 7/5/2017
# https://obrienlabs.net
#

import sys, syslog, time, datetime, json, sqlite3
import requests

databaseFile = "/home/pi/nestapi.sqlite"
iftttEventName = "YOUR_EVENT_NAME"
iftttSecretKey = "YOUR_EVENT_KEY"
nestAPIURL = "https://firebase-apiserver10-tah01-iad01.dapi.production.nest.com:9553/?auth=YOUR_c._NEST_API_KEY"

####################################
# No need to alter anything below  #
####################################
db = sqlite3.connect( databaseFile )
cur = db.cursor()

# Create the table if it doesn't exist
cur.execute("""
    CREATE TABLE IF NOT EXISTS thermostat (
        id INTEGER PRIMARY KEY AUTOINCREMENT, 
        name TEXT not null, 
        online TEXT not null, 
        mode TEXT not null, 
        state TEXT not null, 
        setpoint TEXT not null,
        fanTimerActive TEXT not null,
        fanTimerDuration TEXT not null);
""")
db.commit()

def logmsg( msg ):
    print msg
    syslog.syslog( syslog.LOG_INFO, 'Nest API Notify: %s' % msg )

def update_database( action, name, online, mode, state, targetTemp, fanActive, fanDuration ):
    if action == "insert":
        cur.execute("""
            INSERT INTO thermostat(name, online, mode, state, setpoint, fanTimerActive, fanTimerDuration) VALUES(?, ?, ?, ?, ?, ?, ?)
        """, ( name, mode, online, state, targetTemp, fanActive, fanDuration ) )
    elif action == "update":
        cur.execute("""
           UPDATE thermostat
           SET online=?,mode=?,state=?,setpoint=?,fanTimerActive=?,fanTimerDuration=?
           WHERE name=?
        """, ( online, mode, state, targetTemp, fanActive, fanDuration, name ) )
    db.commit()
    
def send_notification( msg ):
    url = 'https://maker.ifttt.com/trigger/'+iftttEventName+'/with/key/'+iftttSecretKey+''
    headers = {'Content-Type': 'application/json'}
    payload = '{"value1":"'+ msg +'"}'  
    try:
        ret = requests.post(url, headers = headers, data = payload)
        logmsg( "Successfully sent notification to IFTTT: %s\r\n" % msg )
    except Exception, err:
        logmsg( "Error from IFTTT: %s" % str(err).replace("\n", " ") )

def main():
    # Check Nest API
    data = requests.get( nestAPIURL ).json()

    # Loop through the devices
    for key, value in data["devices"]["thermostats"].items():
        push_msg = None
        prevOnline = None
        prevMode = None
        prevState = None
        prevSetpoint = None
        prevFanTimerActive = None
        # key is the thermostat uid, value are the values inside the key
        name = value['name_long']
        online = str( value['is_online'] )
        mode = value['hvac_mode']
        state = value['hvac_state']
        targetTemp = str( value['target_temperature_f'] )
        ambientTemp = str( value['ambient_temperature_f'] )
        fan_timer_active = str( value['fan_timer_active'] )
        fan_timer_duration = str( value['fan_timer_duration'] )
        
        # Get data from database to compare
        cur.execute( """SELECT * FROM thermostat WHERE name=?""", ( name, ) )
        for row in cur.fetchall():
            prevOnline = str( row[2] )
            prevMode = row[3]
            prevState = row[4]
            prevSetpoint = row[5]
            prevFanTimerActive = str( row[6] )
        
        # Populate new database
        if prevOnline is None:
            logmsg( "%s: prevOnline for is None, inserting database with new data." % name )
            update_database( "insert", name, online, mode, state, targetTemp, fan_timer_active, fan_timer_duration )
        
        # Online status check. If thermostat is offline, send the notification and exit script
        if ( ( prevOnline is not None ) and ( online != prevOnline ) ):
            if online == "False":
                push_msg = "%s is offline." % name
                logmsg( push_msg )
                update_database( "update", name, online, mode, state, targetTemp, fan_timer_active, fan_timer_duration )
                send_notification( push_msg )
                sys.exit(1)
            elif online == "True":
                push_msg = "%s is online." % name
                logmsg( push_msg )
                update_database( "update", name, online, mode, state, targetTemp, fan_timer_active, fan_timer_duration )
                send_notification( push_msg )
        else:
            print "%s: No change in online status. Skipping notification." % name
                
        # Create new state push message
        if ( ( prevMode ) and ( mode != prevMode ) ):
            if push_msg is None:
                push_msg = "%s mode is %s" % ( name, mode )
            else:
                push_msg += "and mode is now %s" % mode

        if ( ( prevState ) and ( state != prevState ) ):
            if push_msg is None:
                push_msg = "%s state is %s" % ( name, state )
            else:
                push_msg += " and %s" % state
            
        if ( ( prevSetpoint ) and ( targetTemp != prevSetpoint ) ):
            if push_msg is None:
                push_msg = "%s setpoint is %s" % ( name, targetTemp )
            else:
                push_msg += ". Setpoint %s" % targetTemp
        
        # If prevMode is None then this is a new database. Populate the fields
        if push_msg is not None:
            # If we have push_msg values have changed, update database and send a push notice
            logmsg( "State change, sending notification: %s" % push_msg )
            update_database( "update", name, online, mode, state, targetTemp, fan_timer_active, fan_timer_duration )
            send_notification( push_msg )
        else:
            print "%s: No state change. Skipping notification." % name
            
        # Fan timer active push notice outside of the thermostat loop. Only notify if the system itself is idle. 
        # This is to notify only when the fan timer itself is running not as part of an hvac state
        if ( ( prevFanTimerActive is not None ) and ( state == "off" ) and ( fan_timer_active != prevFanTimerActive ) ):
            print "Checking fan status"
            if fan_timer_active == "True":
                push_msg = "%s: Fan timer now active for %s minutes" % ( name, fan_timer_duration )
            else:
                push_msg = "%s: Fan timer no longer active" % name
            update_database( "update", name, online, mode, state, targetTemp, fan_timer_active, fan_timer_duration )
            send_notification( push_msg )
        else:
            print "%s: No change in fan timer status. Skipping notification." % name

# Start script
if __name__ == '__main__':
    main()
