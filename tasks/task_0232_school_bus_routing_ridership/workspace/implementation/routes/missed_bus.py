"""MissedBusReport endpoints (PRD §3.9)."""

from flask import Blueprint, request

from db import DB, now_clock
from middleware import authenticate, require_role
from response import ok, ok_list
from errors import (
    err, ERR_INVALID_REFERENCE, ERR_INVALID_STATE, ERR_FORBIDDEN,
    ERR_MISSED_BUS_WINDOW,
)
from services import validate as v
from services.common import (
    stamp_create, touch, parse_pagination, sorted_by_creation, paginate,
)
from services.calc import deadline_after
from services.domain import stop_by_sequence, student_has_tap_on, missed_report_public
from services.lookup import get_missed_report
from services.notify import emit

bp = Blueprint("missed_bus", __name__)


@bp.post("/missed-bus-reports")
def file_report():
    p = authenticate()
    require_role(p, {"TransportAdmin", "Parent"})
    body = v.get_body()

    district_id = v.require_str(body, "district_id")
    student_id = v.require_str(body, "student_id")
    bus_trip_id = v.require_str(body, "bus_trip_id")
    reported_stop_sequence = v.require_int(body, "reported_stop_sequence")

    # Body FK resolution — priority 5.
    district = DB.districts.get(district_id)
    student = DB.students.get(student_id)
    trip = DB.bus_trips.get(bus_trip_id)
    if district is None or student is None or trip is None:
        raise err(ERR_INVALID_REFERENCE, "A body reference does not resolve")

    # Parent ownership.
    if p.role == "Parent" and student["parent_id"] != p.user_id:
        raise err(ERR_FORBIDDEN, "Parent may only file for their own student")

    stop = stop_by_sequence(trip["route_id"], reported_stop_sequence)
    if stop is None:
        raise err(ERR_INVALID_REFERENCE, "reported_stop_sequence has no Stop on the trip's route")

    # Window test (PRD §3.9) — all three must hold (priority 19).
    deadline = deadline_after(stop["scheduled_departure"], district["missed_bus_grace_minutes"])
    timely = now_clock() <= deadline
    departed = (trip["current_stop_sequence"] > reported_stop_sequence
                or trip["status"] == "COMPLETED")
    no_tap_on = not student_has_tap_on(student_id, bus_trip_id)

    if not (timely and departed and no_tap_on):
        raise err(ERR_MISSED_BUS_WINDOW, "missed-bus report outside the acceptance window")

    rec = {
        "district_id": district_id,
        "student_id": student_id,
        "bus_trip_id": bus_trip_id,
        "reported_stop_sequence": reported_stop_sequence,
        "status": "OPEN",
        "resolution": None,
    }
    stamp_create(rec)
    DB.missed_bus_reports[rec["id"]] = rec

    emit(district_id, student["parent_id"], student_id, bus_trip_id, "MISSED_BUS",
         {"reported_stop_sequence": reported_stop_sequence})

    return ok(missed_report_public(rec), 201)


@bp.get("/missed-bus-reports/<report_id>")
def get_report_ep(report_id):
    p = authenticate()
    require_role(p, {"TransportAdmin", "Parent"})
    rec = get_missed_report(report_id)
    if p.role == "Parent":
        student = DB.students.get(rec["student_id"])
        if not student or student["parent_id"] != p.user_id:
            raise err(ERR_FORBIDDEN, "Parent may only read their own reports")
    return ok(missed_report_public(rec), 200)


@bp.get("/missed-bus-reports")
def list_reports():
    p = authenticate()
    require_role(p, {"TransportAdmin", "Parent"})
    limit, offset = parse_pagination(request.args)

    records = list(DB.missed_bus_reports.values())
    for field in ("district_id", "student_id", "bus_trip_id", "status"):
        val = request.args.get(field)
        if val is not None:
            records = [r for r in records if r.get(field) == val]

    if p.role == "Parent":
        own = {s["id"] for s in DB.students.values() if s["parent_id"] == p.user_id}
        records = [r for r in records if r["student_id"] in own]

    records = sorted_by_creation(records)
    page, total = paginate(records, limit, offset)
    return ok_list([missed_report_public(r) for r in page], limit, offset, total)


@bp.post("/missed-bus-reports/<report_id>/acknowledge")
def acknowledge(report_id):
    p = authenticate()
    require_role(p, {"TransportAdmin"})
    rec = get_missed_report(report_id)
    if rec["status"] != "OPEN":
        raise err(ERR_INVALID_STATE, "acknowledge requires OPEN")
    rec["status"] = "ACKNOWLEDGED"
    touch(rec)
    return ok(missed_report_public(rec), 200)


@bp.post("/missed-bus-reports/<report_id>/resolve")
def resolve(report_id):
    p = authenticate()
    require_role(p, {"TransportAdmin"})
    rec = get_missed_report(report_id)
    if rec["status"] != "ACKNOWLEDGED":
        raise err(ERR_INVALID_STATE, "resolve requires ACKNOWLEDGED")
    body = v.get_body()
    resolution = v.require_enum(body, "resolution", {"PARENT_PICKUP", "REBOARDED_NEXT_TRIP"})
    rec["status"] = "RESOLVED"
    rec["resolution"] = resolution
    touch(rec)
    return ok(missed_report_public(rec), 200)
