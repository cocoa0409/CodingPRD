"""Dock slots (turnaround-buffer conflict) and parking passes (pool capacity)."""
from datetime import timedelta
from flask import Blueprint

import clock
import db
from errors import ApiError, err_invalid_request, err_invalid_state
from response import ok
from serializers import serialize as _sz, serialize_list as _szl
from services import core as svc
from util import require_auth, get_json, paginate, get_or_404, touch

bp = Blueprint("dockops", __name__)

OM = ["OperationsManager"]
SLOT_READ = ["OperationsManager", "Captain", "DockAttendant"]
DOCK_ATTENDANT = ["DockAttendant"]


# ---------------------------------------------------------------------------
# Dock slots
# ---------------------------------------------------------------------------

@bp.post("/docks/<did>/dock-slots")
def create_dock_slot(did):
    require_auth(OM)
    dock = get_or_404(db.docks, did, "dock", "Dock not found")
    body = get_json(required_fields=["vessel_id", "slot_start", "slot_end"])
    vessel_id = body["vessel_id"]
    if not isinstance(vessel_id, str):
        raise err_invalid_request("vessel_id must be a string")
    start = clock.parse_dt(body["slot_start"])
    end = clock.parse_dt(body["slot_end"])
    if start is None or end is None:
        raise err_invalid_request("slot_start and slot_end must be ISO-8601 datetimes")
    if end <= start:
        raise err_invalid_request("slot_end must be later than slot_start")
    vessel = db.vessels.get(vessel_id)
    if vessel is None:
        from errors import NOT_FOUND_IDS, err_not_found
        raise err_not_found(NOT_FOUND_IDS["vessel"], "Vessel not found")
    # Rung 8: turnaround-buffer overlap for the same vessel, across all docks.
    # Conflict iff a.start < b.end + 45min AND b.start < a.end + 45min.
    # Adjacency exactly at end + 45 minutes is allowed (strict inequality).
    buffer = timedelta(minutes=svc.TURNAROUND_MIN)
    for other in db.dock_slots.values():
        if other["vessel_id"] != vessel["id"]:
            continue
        o_start = clock.parse_dt(other["slot_start"])
        o_end = clock.parse_dt(other["slot_end"])
        if start < o_end + buffer and o_start < end + buffer:
            raise ApiError("ERR_DOCK_SLOT_CONFLICT", 409,
                           "Dock slot conflicts with an existing slot for this vessel")
    now_z = clock.to_z(clock.now())
    slot = {
        "id": db.new_id(), "created_at": now_z, "updated_at": now_z, "version": 1,
        "dock_id": dock["id"], "vessel_id": vessel["id"],
        "slot_start": clock.to_z(start), "slot_end": clock.to_z(end),
    }
    db.insert(db.dock_slots, slot)
    return ok(_sz("dock_slot", slot), status=201)


@bp.get("/dock-slots/<sid>")
def get_dock_slot(sid):
    require_auth(SLOT_READ)
    slot = get_or_404(db.dock_slots, sid, "dock_slot", "Dock slot not found")
    return ok(_sz("dock_slot", slot))


@bp.get("/vessels/<vid>/dock-slots")
def vessel_dock_slots(vid):
    require_auth(SLOT_READ)
    vessel = get_or_404(db.vessels, vid, "vessel", "Vessel not found")
    items = sorted((s for s in db.dock_slots.values() if s["vessel_id"] == vessel["id"]),
                   key=lambda s: s["created_at"])
    page, meta = paginate(items)
    return ok(_szl("dock_slot", page), pagination=meta)


# ---------------------------------------------------------------------------
# Parking passes
# ---------------------------------------------------------------------------

@bp.post("/docks/<did>/parking-passes")
def create_parking_pass(did):
    require_auth(["Customer", "DockAttendant"])
    dock = get_or_404(db.docks, did, "dock", "Dock not found")
    body = get_json(required_fields=["booking_id", "cruise_id"])
    booking_id = body["booking_id"]
    cruise_id = body["cruise_id"]
    if not isinstance(booking_id, str) or not isinstance(cruise_id, str):
        raise err_invalid_request("booking_id and cruise_id must be strings")
    booking = db.bookings.get(booking_id)
    if booking is None:
        from errors import NOT_FOUND_IDS, err_not_found
        raise err_not_found(NOT_FOUND_IDS["booking"], "Booking not found")
    cruise = db.cruises.get(cruise_id)
    if cruise is None:
        from errors import NOT_FOUND_IDS, err_not_found
        raise err_not_found(NOT_FOUND_IDS["cruise"], "Cruise not found")
    # Rung 9: aggregate pool capacity — allowed iff parking_in_use < capacity
    if dock["parking_in_use"] >= dock["parking_capacity"]:
        raise ApiError("ERR_PARKING_FULL", 409, "Dock parking pool at capacity")
    now_z = clock.to_z(clock.now())
    parking_pass = {
        "id": db.new_id(), "created_at": now_z, "updated_at": now_z, "version": 1,
        "dock_id": dock["id"], "booking_id": booking["id"], "cruise_id": cruise["id"],
        "status": "RESERVED",
    }
    db.insert(db.parking_passes, parking_pass)
    svc.recompute_parking_in_use(dock)
    return ok(_sz("parking_pass", parking_pass), status=201)


@bp.get("/parking-passes/<pid>")
def get_parking_pass(pid):
    require_auth(["OperationsManager", "DockAttendant", "Customer"])
    parking_pass = get_or_404(db.parking_passes, pid, "parking_pass", "Parking pass not found")
    return ok(_sz("parking_pass", parking_pass))


@bp.get("/cruises/<cid>/parking-passes")
def cruise_parking_passes(cid):
    require_auth(["OperationsManager", "DockAttendant"])
    cruise = get_or_404(db.cruises, cid, "cruise", "Cruise not found")
    items = sorted((p for p in db.parking_passes.values() if p["cruise_id"] == cruise["id"]),
                   key=lambda p: p["created_at"])
    page, meta = paginate(items)
    return ok(_szl("parking_pass", page), pagination=meta)


@bp.post("/parking-passes/<pid>/redeem")
def redeem_parking_pass(pid):
    require_auth(DOCK_ATTENDANT)
    parking_pass = get_or_404(db.parking_passes, pid, "parking_pass", "Parking pass not found")
    if parking_pass["status"] != "RESERVED":
        raise err_invalid_state("Parking pass is not RESERVED")
    cruise = db.cruises.get(parking_pass["cruise_id"])
    if cruise is None or cruise["status"] not in ("SCHEDULED", "BOARDING"):
        raise err_invalid_state("Cruise is not SCHEDULED or BOARDING")
    parking_pass["status"] = "REDEEMED"
    touch(parking_pass)
    return ok(_sz("parking_pass", parking_pass))


@bp.post("/parking-passes/<pid>/release")
def release_parking_pass(pid):
    require_auth(DOCK_ATTENDANT)
    parking_pass = get_or_404(db.parking_passes, pid, "parking_pass", "Parking pass not found")
    if parking_pass["status"] != "RESERVED":
        raise err_invalid_state("Parking pass is not RESERVED")
    parking_pass["status"] = "RELEASED"
    touch(parking_pass)
    dock = db.docks.get(parking_pass["dock_id"])
    if dock is not None:
        svc.recompute_parking_in_use(dock)
    return ok(_sz("parking_pass", parking_pass))
