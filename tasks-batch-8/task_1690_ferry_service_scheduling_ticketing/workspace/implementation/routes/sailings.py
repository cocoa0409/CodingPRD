"""Sailing endpoints (PRD §3.3, §3.4, §3.7, §3.8)."""

from flask import Blueprint, request

from db import db, now_iso, _parse_iso
from errors import (
    raise_error, ERR_NOT_FOUND, ERR_INVALID_STATE, ERR_SAILING_NOT_BOOKABLE,
    ERR_MANNING_SHORTFALL, ERR_VESSEL_SCHEDULE_CONFLICT,
    ERR_FARE_SCHEDULE_NOT_EFFECTIVE,
)
from middleware import require_roles
from response import success_object, success_list, parse_pagination, paginate
from services.calculations import (
    touch, recompute_sailing_counters, crew_manning_compliance,
    vehicle_deck_allocation,
)
from services.fare_schedule import find_effective_schedule
from services.serializers import (
    serialize_sailing, serialize_booking, serialize_standby_entry,
    serialize_crew_assignment,
)
from services.sailing_ops import (
    cancel_sailing_cascade, depart_sailing, complete_sailing,
    begin_boarding_sailing,
)

bp = Blueprint("sailings", __name__)

ALL_ROLES = ("SchedulerAdmin", "TerminalAgent", "CrewPlanner", "Customer")
CANCELABLE_STATUSES = ("SCHEDULED", "OPEN_FOR_BOOKING", "BOOKING_CLOSED", "BOARDING")


def _get_sailing(sailing_id):
    s = db.sailings.get(sailing_id)
    if s is None:
        raise_error(ERR_NOT_FOUND, "Sailing not found")
    return s


@bp.post("/ferry/routes/<route_id>/sailings")
def create_sailing(route_id):
    require_roles("SchedulerAdmin")
    route = db.routes.get(route_id)
    if route is None:
        raise_error(ERR_NOT_FOUND, "Route not found")

    payload = request.get_json(silent=True) or {}
    vessel = db.vessels.get(payload.get("vessel_id"))
    if vessel is None:
        raise_error(ERR_NOT_FOUND, "Vessel not found")

    departure = _parse_iso(payload.get("departure_time"))
    from datetime import timedelta
    arrival = departure + timedelta(minutes=int(route["crossing_minutes"]))
    turnaround = timedelta(minutes=int(route["turnaround_minutes"]))

    # Priority 9: vessel temporal overlap — occupied window is
    # [departure_time, arrival_time + turnaround), half-open.
    new_start = departure
    new_end = arrival + turnaround
    for s in db.sailings.values():
        if s["vessel_id"] != vessel["id"] or s["status"] == "CANCELLED":
            continue
        ex_start = _parse_iso(s["departure_time"])
        ex_arrival = _parse_iso(s["arrival_time"])
        ex_route = db.routes.get(s["route_id"])
        ex_turn = timedelta(minutes=int(ex_route["turnaround_minutes"])) if ex_route else timedelta(0)
        ex_end = ex_arrival + ex_turn
        if new_start < ex_end and ex_start < new_end:
            raise_error(ERR_VESSEL_SCHEDULE_CONFLICT,
                        "Sailing would overlap another sailing of the same vessel "
                        "within the turnaround buffer")

    from db import iso_out
    ts = now_iso()
    sailing = {
        "id": db.new_id(),
        "route_id": route_id,
        "vessel_id": vessel["id"],
        "departure_time": payload.get("departure_time"),
        "arrival_time": iso_out(arrival),
        "season": payload.get("season"),
        "status": "SCHEDULED",
        "cancel_reason": None,
        "reserved_vehicle_feet": 0,
        "standby_cleared_feet": 0,
        "booked_passengers": 0,
        "reserved_deck_allotment_feet": 0,
        "manning_ok": False,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    db.sailings[sailing["id"]] = sailing
    sailing["manning_ok"] = crew_manning_compliance(sailing)
    return success_object(serialize_sailing(sailing), status=201)


@bp.get("/ferry/sailings/<sailing_id>")
def get_sailing(sailing_id):
    require_roles(*ALL_ROLES)
    sailing = _get_sailing(sailing_id)
    return success_object(serialize_sailing(sailing))


@bp.get("/ferry/sailings")
def list_sailings():
    require_roles(*ALL_ROLES)
    vessel_id = request.args.get("vessel_id")
    status = request.args.get("status")
    season = request.args.get("season")
    items = [s for s in db.sailings.values()
             if (vessel_id is None or s["vessel_id"] == vessel_id)
             and (status is None or s["status"] == status)
             and (season is None or s["season"] == season)]
    items.sort(key=lambda s: (s["created_at"], s["id"]))
    limit, offset = parse_pagination(request.args)
    page, meta = paginate(items, limit, offset)
    return success_list([serialize_sailing(s) for s in page], meta)


@bp.get("/ferry/sailings/<sailing_id>/bookings")
def list_sailing_bookings(sailing_id):
    require_roles(*ALL_ROLES)
    _get_sailing(sailing_id)
    status = request.args.get("status")
    customer_id = request.args.get("customer_id")
    items = [b for b in db.bookings.values()
             if b["sailing_id"] == sailing_id
             and (status is None or b["status"] == status)
             and (customer_id is None or b["customer_id"] == customer_id)]
    items.sort(key=lambda b: (b["created_at"], b["id"]))
    limit, offset = parse_pagination(request.args)
    page, meta = paginate(items, limit, offset)
    return success_list([serialize_booking(b) for b in page], meta)


@bp.get("/ferry/sailings/<sailing_id>/standby-queue")
def list_sailing_standby(sailing_id):
    require_roles(*ALL_ROLES)
    _get_sailing(sailing_id)
    status = request.args.get("status")
    items = [e for e in db.standby_entries.values()
             if e["sailing_id"] == sailing_id
             and (status is None or e["status"] == status)]
    items.sort(key=lambda e: (e["created_at"], e["id"]))
    limit, offset = parse_pagination(request.args)
    page, meta = paginate(items, limit, offset)
    return success_list([serialize_standby_entry(e) for e in page], meta)


@bp.get("/ferry/sailings/<sailing_id>/crew-assignments")
def list_sailing_crew_assignments(sailing_id):
    require_roles("SchedulerAdmin", "TerminalAgent", "CrewPlanner")
    _get_sailing(sailing_id)
    status = request.args.get("status")
    items = [a for a in db.crew_assignments.values()
             if a["sailing_id"] == sailing_id
             and (status is None or a["status"] == status)]
    items.sort(key=lambda a: (a["created_at"], a["id"]))
    limit, offset = parse_pagination(request.args)
    page, meta = paginate(items, limit, offset)
    return success_list([serialize_crew_assignment(a) for a in page], meta)


@bp.get("/ferry/sailings/<sailing_id>/deck-projection")
def deck_projection(sailing_id):
    """What-if deck split under a caller-supplied ratio (dynamic_ratio_variant).
    Read-only: never mutates the pinned allotment (§3.4)."""
    require_roles("SchedulerAdmin", "TerminalAgent")
    sailing = _get_sailing(sailing_id)
    vessel = db.vessels[sailing["vessel_id"]]
    ratio = request.args.get("ratio")
    reserved, standby = vehicle_deck_allocation(
        vessel["vehicle_deck_linear_feet"], ratio=ratio)
    return success_object({
        "reserved_deck_allotment_feet": reserved,
        "standby_pool_feet": standby,
    })


@bp.post("/ferry/sailings/<sailing_id>/open-booking")
def open_booking(sailing_id):
    require_roles("SchedulerAdmin")
    sailing = _get_sailing(sailing_id)

    # Priority 4: legal state (SCHEDULED -> OPEN_FOR_BOOKING only)
    if sailing["status"] != "SCHEDULED":
        raise_error(ERR_INVALID_STATE,
                    f"Cannot open booking for a sailing in status {sailing['status']}")

    route = db.routes[sailing["route_id"]]
    vessel = db.vessels[sailing["vessel_id"]]

    if route["status"] != "ACTIVE":
        raise_error(ERR_INVALID_STATE, "Route is not ACTIVE")
    if vessel["status"] != "IN_SERVICE":
        raise_error(ERR_INVALID_STATE, "Vessel is not IN_SERVICE")

    # EFFECTIVE fare schedule must cover route+season at departure_time
    departure = _parse_iso(sailing["departure_time"])
    fs = find_effective_schedule(sailing["route_id"], sailing["season"], at_dt=departure)
    if fs is None:
        raise_error(ERR_FARE_SCHEDULE_NOT_EFFECTIVE,
                    "No EFFECTIVE fare schedule covers the sailing's route+season")

    # Priority 8: manning gate
    sailing["manning_ok"] = crew_manning_compliance(sailing)
    if not sailing["manning_ok"]:
        raise_error(ERR_MANNING_SHORTFALL,
                    "Coast Guard manning minimums not met")

    # Pin the deck split (vehicle_deck_allocation) at open time (§3.4)
    reserved, _standby = vehicle_deck_allocation(
        vessel["vehicle_deck_linear_feet"], season=sailing["season"])
    sailing["reserved_deck_allotment_feet"] = reserved
    sailing["status"] = "OPEN_FOR_BOOKING"
    recompute_sailing_counters(sailing)
    touch(sailing)
    return success_object(serialize_sailing(sailing))


@bp.post("/ferry/sailings/<sailing_id>/close-booking")
def close_booking(sailing_id):
    require_roles("SchedulerAdmin")
    sailing = _get_sailing(sailing_id)
    if sailing["status"] != "OPEN_FOR_BOOKING":
        raise_error(ERR_INVALID_STATE,
                    f"Cannot close booking for a sailing in status {sailing['status']}")
    sailing["status"] = "BOOKING_CLOSED"
    touch(sailing)
    return success_object(serialize_sailing(sailing))


@bp.post("/ferry/sailings/<sailing_id>/begin-boarding")
def begin_boarding(sailing_id):
    require_roles("TerminalAgent")
    sailing = _get_sailing(sailing_id)
    if sailing["status"] != "BOOKING_CLOSED":
        raise_error(ERR_INVALID_STATE,
                    f"Cannot begin boarding for a sailing in status {sailing['status']}")
    sailing["manning_ok"] = crew_manning_compliance(sailing)
    if not sailing["manning_ok"]:
        raise_error(ERR_MANNING_SHORTFALL,
                    "Coast Guard manning minimums not met")
    begin_boarding_sailing(sailing)
    return success_object(serialize_sailing(sailing))


@bp.post("/ferry/sailings/<sailing_id>/depart")
def depart(sailing_id):
    require_roles("TerminalAgent")
    sailing = _get_sailing(sailing_id)
    if sailing["status"] != "BOARDING":
        raise_error(ERR_INVALID_STATE,
                    f"Cannot depart a sailing in status {sailing['status']}")
    depart_sailing(sailing)
    return success_object(serialize_sailing(sailing))


@bp.post("/ferry/sailings/<sailing_id>/complete")
def complete(sailing_id):
    require_roles("TerminalAgent")
    sailing = _get_sailing(sailing_id)
    if sailing["status"] != "DEPARTED":
        raise_error(ERR_INVALID_STATE,
                    f"Cannot complete a sailing in status {sailing['status']}")
    complete_sailing(sailing)
    return success_object(serialize_sailing(sailing))


@bp.post("/ferry/sailings/<sailing_id>/cancel")
def cancel(sailing_id):
    require_roles("SchedulerAdmin")
    sailing = _get_sailing(sailing_id)
    if sailing["status"] not in CANCELABLE_STATUSES:
        raise_error(ERR_INVALID_STATE,
                    f"Cannot cancel a sailing in status {sailing['status']}")
    payload = request.get_json(silent=True) or {}
    cancel_sailing_cascade(sailing, payload.get("cancel_reason"))
    return success_object(serialize_sailing(sailing))
