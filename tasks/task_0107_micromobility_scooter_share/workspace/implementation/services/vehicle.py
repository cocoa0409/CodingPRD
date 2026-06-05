"""Vehicle status-timeline recording (PRD §3.8 support).

The MDS time-weighted availability figure integrates the count of AVAILABLE
vehicles across a window using vehicle status-change events. Because the store
keeps only each vehicle's current status, we maintain an append-only timeline of
(vehicle_id, status, at) events: one when the vehicle is registered and one on
every status mutation. A vehicle's status at any instant is the status from the
most recent event at or before that instant.
"""
from clock import now
from db import db


def record_status_event(vehicle):
    """Append a status-change event stamped at the current logical clock."""
    db.vehicle_status_events.append({
        "vehicle_id": vehicle["id"],
        "status": vehicle["status"],
        "at": now(),
        "_seq": db.next_seq(),
    })


def set_status(vehicle, new_status):
    """Set a vehicle's status and append a timeline event when it changes."""
    if vehicle["status"] != new_status:
        vehicle["status"] = new_status
        record_status_event(vehicle)
