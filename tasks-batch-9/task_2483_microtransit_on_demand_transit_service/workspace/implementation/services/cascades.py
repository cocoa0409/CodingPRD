"""Ordered cascades (PRD Section 2.10)."""
import calculations as calc
import clock
import db
from services import blocks as block_service
from services import fares
from services import metrics


def _block_order_key(block):
    return (clock.parse_dt(block["start_utc"]), block["created_at"], block["_seq"])


def clear_trip_booking(trip):
    trip["assigned_block_id"] = None
    trip["projected_detour_minutes"] = None
    trip["promised_pickup_utc"] = None
    trip["promised_dropoff_utc"] = None
    fares.void_quote(trip)


def requeue_or_exhaust(trip):
    """Un-book a trip whose offer went away, then re-queue it or exhaust it."""
    clear_trip_booking(trip)
    if trip["match_attempt_count"] < calc.MAX_MATCH_ATTEMPTS:
        trip["status"] = "MATCHING"
        db.touch(trip)
    else:
        trip["status"] = "NO_SERVICE"
        trip["no_service_reason"] = "MAX_ATTEMPTS_EXHAUSTED"
        db.touch(trip)
        metrics.recompute_zone_by_id(trip["zone_id"])


def release_assignment(assignment):
    assignment["state"] = "RELEASED"
    db.touch(assignment)


# --------------------------------------------------------------------------
# zone suspension sweep
# --------------------------------------------------------------------------

def sweep_zone_suspension(zone):
    trips = [t for t in db.trip_requests.values()
             if t["zone_id"] == zone["id"]
             and t["status"] in ("RECEIVED", "MATCHING")]
    for trip in db.by_created_at(trips):
        trip["status"] = "NO_SERVICE"
        trip["no_service_reason"] = "ZONE_SUSPENDED"
        trip["assigned_block_id"] = None
        fares.void_quote(trip)
        db.touch(trip)


# --------------------------------------------------------------------------
# driver suspension sweep
# --------------------------------------------------------------------------

def suspend_driver(driver):
    driver["status"] = "SUSPENDED"
    db.touch(driver)
    scheduled = [b for b in db.vehicle_blocks.values()
                 if b["driver_id"] == driver["id"] and b["state"] == "SCHEDULED"]
    for block in sorted(scheduled, key=_block_order_key):
        block["state"] = "CANCELLED"
        db.touch(block)


# --------------------------------------------------------------------------
# open-block cancellation: the largest cascade in the system
# --------------------------------------------------------------------------

def cancel_open_block(block):
    # HOP 1 -- zero the block's own commitments
    block["seats_committed"] = 0
    block["wav_positions_committed"] = 0
    block["committed_index_min"] = None
    block["committed_index_max"] = None

    # HOP 2 -- release the manifest, in assignment created_at ASC order
    releasable = [a for a in block_service.assignments_of(block["id"])
                  if a["state"] in ("OFFERED", "ACCEPTED")]
    released = []
    for assignment in db.by_created_at(releasable):
        release_assignment(assignment)
        released.append(assignment)

    # HOP 3 / HOP 4 -- un-book each released trip, re-queueing or exhausting it
    for assignment in released:
        trip = db.trip_requests.get(assignment["trip_request_id"])
        if trip is None or trip["status"] not in ("OFFERED", "ASSIGNED"):
            continue
        requeue_or_exhaust(trip)

    block["state"] = "CANCELLED"
    block_service.recompute_block(block)
    db.touch(block)


# --------------------------------------------------------------------------
# trip cancellation with a live offer
# --------------------------------------------------------------------------

def release_live_assignment_for_trip(trip):
    """Give back the offer a cancelling trip still holds."""
    for assignment in db.by_created_at(
            [a for a in db.pool_assignments.values()
             if a["trip_request_id"] == trip["id"]
             and a["state"] in ("OFFERED", "ACCEPTED")]):
        release_assignment(assignment)
        block = db.vehicle_blocks.get(assignment["block_id"])
        if block is not None:
            block_service.recompute_block(block)
