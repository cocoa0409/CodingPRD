"""Tour slot endpoints."""
from datetime import timedelta

from flask import Blueprint

from db import DB, new_id, now
from errors import ApiError
from middleware import ALL_ROLES, auth
from response import ok, ok_list
from services import (
    cancel_slot_cascade,
    check_occupancy_conflict,
    check_shift_overlap,
    lookup,
    ser_booking,
    ser_incident,
    ser_shift,
    ser_slot,
    ser_survey,
    slot_shifts,
    sort_items,
    staffing_status,
    stamp,
    touch,
)
from util import body, pagination_args, req_enum, req_int, req_iso_dt

bp = Blueprint("slots", __name__)

KIND_BUFFER = {"STANDARD": 2, "SCHOOL": 0, "CANDLELIGHT": 4}


def _paginate(items, serializer):
    limit, offset = pagination_args()
    total = len(items)
    page = items[offset : offset + limit]
    return ok_list([serializer(x) for x in page], total, limit, offset)


@bp.post("/tour-slots")
def create_slot():
    auth(["MuseumAdmin"])
    data = body()
    # Tier 3 (existence): body FK route_id.
    raw_route = data.get("route_id")
    route = lookup("routes", raw_route) if raw_route is not None else None
    # Tier 4 (request shape).
    if raw_route is None:
        # Missing route_id is a shape failure once existence is moot.
        raise ApiError("ERR_INVALID_REQUEST", 400, "Missing required field: route_id")
    _, start_dt = req_iso_dt(data, "start_at")
    # Tier 9 (cross-entity): route must be ACTIVE.
    if route["status"] != "ACTIVE":
        raise ApiError("ERR_ROUTE_NOT_ACTIVE", 409, "Route is not ACTIVE")
    # Tier 10 (temporal): start strictly after the logical clock.
    if start_dt <= now():
        raise ApiError(
            "ERR_SLOT_IN_PAST",
            422,
            "start_at must be strictly after the logical clock",
        )
    end_dt = start_dt + timedelta(minutes=route["duration_minutes"])
    check_occupancy_conflict(route, start_dt, end_dt)
    raw_min = min(DB["rooms"][rid]["capacity_max"] for rid in route["room_ids"])
    capacity = max(1, raw_min - KIND_BUFFER[route["kind"]])
    rec = {
        "id": new_id(),
        "route_id": route["id"],
        "_start_dt": start_dt,
        "_end_dt": end_dt,
        "capacity": capacity,
        "status": "SCHEDULED",
        "_completed_dt": None,
    }
    stamp(rec)
    DB["slots"][rec["id"]] = rec
    return ok(ser_slot(rec), 201)


@bp.get("/tour-slots/<sid>")
def get_slot(sid):
    auth(ALL_ROLES)
    return ok(ser_slot(lookup("slots", sid)))


@bp.post("/tour-slots/<sid>/open")
def open_slot(sid):
    auth(["MuseumAdmin"])
    slot = lookup("slots", sid)
    if slot["status"] != "SCHEDULED":
        raise ApiError(
            "ERR_INVALID_STATE", 409, "Only a SCHEDULED slot can be opened"
        )
    route = lookup("routes", slot["route_id"])
    if route["status"] != "ACTIVE":
        raise ApiError("ERR_ROUTE_NOT_ACTIVE", 409, "Route is not ACTIVE")
    if route["published_script_id"] is None:
        raise ApiError(
            "ERR_SCRIPT_NOT_PUBLISHED", 409, "Route has no published script"
        )
    for rid in route["room_ids"]:
        if DB["rooms"][rid]["status"] != "OPEN":
            raise ApiError(
                "ERR_ROOM_CLOSED", 409, "A room on this route is closed"
            )
    if staffing_status(slot) != "STAFFED":
        raise ApiError(
            "ERR_SLOT_NOT_STAFFED", 409, "Slot has no confirmed LEAD shift"
        )
    slot["status"] = "OPEN"
    touch(slot)
    return ok(ser_slot(slot))


@bp.post("/tour-slots/<sid>/advance")
def advance_slot(sid):
    auth(["MuseumAdmin", "FrontDeskStaff"])
    slot = lookup("slots", sid)
    data = body()
    to_status = req_enum(data, "to_status", ("IN_PROGRESS", "COMPLETED"))
    if to_status == "IN_PROGRESS":
        if slot["status"] not in ("OPEN", "FULL"):
            raise ApiError(
                "ERR_INVALID_STATE",
                409,
                "Only an OPEN or FULL slot can start",
            )
        if now() < slot["_start_dt"]:
            raise ApiError(
                "ERR_INVALID_STATE", 409, "Slot cannot start before start_at"
            )
        slot["status"] = "IN_PROGRESS"
    else:  # COMPLETED
        if slot["status"] != "IN_PROGRESS":
            raise ApiError(
                "ERR_INVALID_STATE",
                409,
                "Only an IN_PROGRESS slot can complete",
            )
        slot["status"] = "COMPLETED"
        slot["_completed_dt"] = now()
    touch(slot)
    return ok(ser_slot(slot))


@bp.post("/tour-slots/<sid>/cancel")
def cancel_slot(sid):
    auth(["MuseumAdmin"])
    slot = lookup("slots", sid)
    if slot["status"] not in ("SCHEDULED", "OPEN", "FULL"):
        raise ApiError(
            "ERR_INVALID_STATE",
            409,
            "Only a SCHEDULED, OPEN, or FULL slot can be cancelled",
        )
    # Manual cancellation keeps the time-tier refund rule (PRD 3.4, 3.6).
    cancel_slot_cascade(slot, full_refund=False)
    return ok(ser_slot(slot))


@bp.post("/tour-slots/<sid>/reschedule")
def reschedule_slot(sid):
    auth(["MuseumAdmin"])
    slot = lookup("slots", sid)
    data = body()
    _, start_dt = req_iso_dt(data, "start_at")
    expected = req_int(data, "expected_slot_version")
    if slot["status"] not in ("SCHEDULED", "OPEN"):
        raise ApiError(
            "ERR_INVALID_STATE",
            409,
            "Only a SCHEDULED or OPEN slot can be rescheduled",
        )
    if expected != slot["version"]:
        raise ApiError(
            "ERR_STALE_VERSION",
            412,
            "expected_slot_version does not match the slot's current version",
        )
    if start_dt <= now():
        raise ApiError(
            "ERR_SLOT_IN_PAST",
            422,
            "start_at must be strictly after the logical clock",
        )
    route = lookup("routes", slot["route_id"])
    end_dt = start_dt + timedelta(minutes=route["duration_minutes"])
    # Tier 10 order (PRD 2.9): shift buffer overlap before room occupancy.
    rostered = {
        s["docent_id"]
        for s in slot_shifts(slot["id"])
        if s["status"] in ("ASSIGNED", "CONFIRMED")
    }
    for doc_id in rostered:
        check_shift_overlap(doc_id, start_dt, end_dt, exclude_slot_id=slot["id"])
    check_occupancy_conflict(route, start_dt, end_dt, exclude_slot_id=slot["id"])
    slot["_start_dt"] = start_dt
    slot["_end_dt"] = end_dt
    touch(slot)
    return ok(ser_slot(slot))


@bp.get("/tour-slots/<sid>/bookings")
def list_slot_bookings(sid):
    auth(["MuseumAdmin", "FrontDeskStaff"])
    slot = lookup("slots", sid)
    items = sort_items(
        [b for b in DB["bookings"].values() if b["slot_id"] == slot["id"]]
    )
    return _paginate(items, ser_booking)


@bp.get("/tour-slots/<sid>/shifts")
def list_slot_shifts(sid):
    auth(["MuseumAdmin", "DocentCoordinator", "Docent"])
    slot = lookup("slots", sid)
    items = sort_items(
        [s for s in DB["shifts"].values() if s["slot_id"] == slot["id"]]
    )
    return _paginate(items, ser_shift)


@bp.get("/tour-slots/<sid>/incidents")
def list_slot_incidents(sid):
    auth(["MuseumAdmin", "Curator"])
    slot = lookup("slots", sid)
    items = sort_items(
        [i for i in DB["incidents"].values() if i["slot_id"] == slot["id"]]
    )
    return _paginate(items, ser_incident)


@bp.get("/tour-slots/<sid>/surveys")
def list_slot_surveys(sid):
    auth(ALL_ROLES)
    slot = lookup("slots", sid)
    items = sort_items(
        [s for s in DB["surveys"].values() if s["slot_id"] == slot["id"]]
    )
    return _paginate(items, ser_survey)
