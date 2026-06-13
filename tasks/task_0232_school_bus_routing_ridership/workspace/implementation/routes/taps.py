"""TapEvent endpoints (PRD §3.7)."""

from flask import Blueprint, request

from db import DB
from middleware import authenticate, require_role
from response import ok, ok_list
from errors import (
    err, ERR_INVALID_REFERENCE, ERR_INVALID_STATE, ERR_FORBIDDEN,
    ERR_NOT_ASSIGNED_RIDER, ERR_TAP_SEQUENCE,
)
from services import validate as v
from services.common import (
    stamp_create, touch, parse_pagination, sorted_by_creation, paginate,
)
from services.domain import onboard_set, tap_event_public, bus_trip_public
from services.lookup import get_bus_trip, get_tap_event
from services.notify import emit

bp = Blueprint("taps", __name__)


def _trip_driver_id(trip):
    asg = DB.driver_assignments.get(trip["driver_assignment_id"])
    return asg["driver_id"] if asg else None


@bp.post("/bus-trips/<bus_trip_id>/taps")
def record_tap(bus_trip_id):
    p = authenticate()
    require_role(p, {"Driver"})
    trip = get_bus_trip(bus_trip_id)

    if p.role == "Driver" and _trip_driver_id(trip) != p.user_id:
        raise err(ERR_FORBIDDEN, "Driver does not own this trip")

    body = v.get_body()
    rfid_uid = v.require_str(body, "rfid_uid")
    direction = v.require_enum(body, "direction", {"TAP_ON", "TAP_OFF"})
    stop_sequence = v.require_int(body, "stop_sequence")

    # Resolve rfid_uid -> a Student in this trip's route's district — priority 5.
    route = DB.routes.get(trip["route_id"])
    district_id = route["district_id"] if route else None
    student = None
    for s in DB.students.values():
        if s["district_id"] == district_id and s["rfid_uid"] == rfid_uid:
            student = s
            break
    if student is None:
        raise err(ERR_INVALID_REFERENCE, "rfid_uid does not resolve to a Student in the District")

    # stop_sequence must equal the trip's current_stop_sequence.
    if stop_sequence != trip["current_stop_sequence"]:
        raise err(ERR_INVALID_STATE, "stop_sequence must equal current_stop_sequence")

    # The student must have an APPROVED application on this route — priority 13.
    has_assignment = any(
        a["status"] == "APPROVED"
        and a["assigned_route_id"] == trip["route_id"]
        and a["student_id"] == student["id"]
        for a in DB.ridership_applications.values()
    )
    if not has_assignment:
        raise err(ERR_NOT_ASSIGNED_RIDER, "student has no APPROVED ridership on this route")

    # Tap ordering — priority 14.
    onboard = onboard_set(trip["id"])
    if direction == "TAP_ON" and student["id"] in onboard:
        raise err(ERR_TAP_SEQUENCE, "student is already onboard")
    if direction == "TAP_OFF" and student["id"] not in onboard:
        raise err(ERR_TAP_SEQUENCE, "no prior unmatched TAP_ON for this student")

    rec = {
        "bus_trip_id": trip["id"],
        "student_id": student["id"],
        "rfid_uid": rfid_uid,
        "direction": direction,
        "stop_sequence": stop_sequence,
    }
    stamp_create(rec, common_fields=False)
    DB.tap_events[rec["id"]] = rec

    # onboard_count is computed live; the trip is mutated by this tap.
    touch(trip)

    emit(student["district_id"], student["parent_id"], student["id"], trip["id"],
         direction, {"stop_sequence": stop_sequence})

    return ok(tap_event_public(rec), 201)


@bp.get("/tap-events/<tap_event_id>")
def get_tap_event_ep(tap_event_id):
    p = authenticate()
    require_role(p, {"TransportAdmin", "Parent", "Driver"})
    rec = get_tap_event(tap_event_id)
    return ok(tap_event_public(rec), 200)


@bp.get("/tap-events")
def list_tap_events():
    p = authenticate()
    require_role(p, {"TransportAdmin", "Parent", "Driver"})
    limit, offset = parse_pagination(request.args)

    records = list(DB.tap_events.values())
    for field in ("bus_trip_id", "student_id", "direction"):
        val = request.args.get(field)
        if val is not None:
            records = [r for r in records if r.get(field) == val]

    records = sorted_by_creation(records)
    page, total = paginate(records, limit, offset)
    return ok_list([tap_event_public(r) for r in page], limit, offset, total)
