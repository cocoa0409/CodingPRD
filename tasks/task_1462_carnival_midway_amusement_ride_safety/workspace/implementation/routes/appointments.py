"""Inspection appointments: schedule (auto-assign), read, list, complete, cancel."""
from flask import Blueprint

import db
from db import serialize, touch
from errors import (
    raise_err,
    ERR_INVALID_REQUEST,
    ERR_FAIR_INVALID_STATE,
    ERR_APPOINTMENT_INVALID_STATE,
    ERR_APPOINTMENT_NOT_DUE,
    ERR_APPOINTMENT_WINDOW_INVALID,
    ERR_INSPECTOR_UNAVAILABLE,
    ERR_CROSS_FAIR_REFERENCE,
)
from helpers import get_or_404, paginate, qparam, _parse_date
from middleware import authenticate, scope_to_fair, require_owner
from response import ok
from services.calculations import assign_inspector
from validators import get_body, reject_unknown, req_str, req_int, req_enum, req_date, opt_str

bp = Blueprint("appointments", __name__)

ALL = ["StateProgramAdmin", "StateInspector", "FairManager", "RideOperator", "TicketClerk", "CrewMember"]

APPOINTMENT_FIELDS = {"fair_id", "scope", "ride_id", "scheduled_date", "start_hour", "duration_hours"}


@bp.post("/inspection-appointments")
def create_appointment():
    ctx = authenticate(["FairManager"])
    body = get_body()
    reject_unknown(body, APPOINTMENT_FIELDS)
    fair_id = req_str(body, "fair_id")
    scope = req_enum(body, "scope", ["FAIR_WIDE", "RIDE_AUDIT"])
    scheduled = req_date(body, "scheduled_date")
    start_hour = req_int(body, "start_hour", lo=6, hi=20)
    duration = req_int(body, "duration_hours", lo=1, hi=4)
    if start_hour + duration > 21:
        raise_err(ERR_INVALID_REQUEST, "end_hour (start_hour + duration_hours) must be <= 21")
    ride_id = body.get("ride_id")
    if scope == "RIDE_AUDIT":
        if ride_id is None:
            raise_err(ERR_INVALID_REQUEST, "ride_id is required for scope RIDE_AUDIT")
        if not isinstance(ride_id, str) or ride_id.strip() == "":
            raise_err(ERR_INVALID_REQUEST, "ride_id must be a string")
    else:
        if ride_id is not None:
            raise_err(ERR_INVALID_REQUEST, "ride_id is forbidden for scope FAIR_WIDE")

    scope_to_fair(ctx, fair_id if db.get("fairs", fair_id) else None)
    fair = get_or_404("fairs", fair_id)
    scope_to_fair(ctx, fair["id"])
    ride = None
    if scope == "RIDE_AUDIT":
        ride = get_or_404("rides", ride_id)

    if fair["status"] not in ("PERMIT_REQUESTED", "PERMITTED"):
        raise_err(ERR_FAIR_INVALID_STATE, "Appointments require the fair to be PERMIT_REQUESTED or PERMITTED")

    inspector = assign_inspector(body["scheduled_date"], start_hour, duration)
    if inspector is None:
        raise_err(ERR_INSPECTOR_UNAVAILABLE, "No eligible inspector is available")

    today = db.today_date()
    if not (today <= scheduled <= _parse_date(fair["teardown_end_date"])):
        raise_err(ERR_APPOINTMENT_WINDOW_INVALID, "scheduled_date must be within [current date, teardown_end_date]")

    if scope == "RIDE_AUDIT" and ride["fair_id"] != fair["id"]:
        raise_err(ERR_CROSS_FAIR_REFERENCE, "The ride does not belong to the named fair")

    appointment = db.register(
        "appointments",
        {
            "fair_id": fair_id,
            "inspector_id": inspector["id"],
            "ride_id": ride_id if scope == "RIDE_AUDIT" else None,
            "scope": scope,
            "scheduled_date": body["scheduled_date"],
            "start_hour": start_hour,
            "duration_hours": duration,
            "end_hour": start_hour + duration,
            "status": "SCHEDULED",
            "findings": None,
            "completed_at": None,
        },
    )
    return ok(serialize(appointment), 201)


@bp.get("/inspection-appointments/<aid>")
def get_appointment(aid):
    ctx = authenticate(ALL)
    appointment = get_or_404("appointments", aid)
    scope_to_fair(ctx, appointment["fair_id"])
    return ok(serialize(appointment))


@bp.get("/inspection-appointments")
def list_appointments():
    authenticate(ALL)
    return paginate(
        "appointments",
        {
            "fair_id": qparam("fair_id"),
            "inspector_id": qparam("inspector_id"),
            "ride_id": qparam("ride_id"),
            "scheduled_date": qparam("scheduled_date"),
            "status": qparam("status"),
        },
    )


@bp.post("/inspection-appointments/<aid>/complete")
def complete_appointment(aid):
    ctx = authenticate(["StateInspector"])
    appointment = get_or_404("appointments", aid)
    require_owner(ctx["user_id"] == appointment["inspector_id"])
    body = get_body()
    reject_unknown(body, {"outcome", "findings"})
    outcome = req_enum(body, "outcome", ["PASS", "FAIL"])
    findings = opt_str(body, "findings")
    if appointment["status"] != "SCHEDULED":
        raise_err(ERR_APPOINTMENT_INVALID_STATE, "Only a SCHEDULED appointment can be completed")
    if appointment["scope"] == "RIDE_AUDIT":
        fair = db.get("fairs", appointment["fair_id"])
        if fair["status"] != "PERMITTED":
            raise_err(ERR_FAIR_INVALID_STATE, "A RIDE_AUDIT completion requires the fair to be PERMITTED")
    if _parse_date(appointment["scheduled_date"]) > db.today_date():
        raise_err(ERR_APPOINTMENT_NOT_DUE, "The appointment cannot be completed before its scheduled date")

    appointment["status"] = "COMPLETED_PASS" if outcome == "PASS" else "COMPLETED_FAIL"
    appointment["completed_at"] = db.now_iso()
    if findings is not None:
        appointment["findings"] = findings
    touch(appointment)

    if outcome == "PASS" and appointment["scope"] == "RIDE_AUDIT":
        ride = db.get("rides", appointment["ride_id"])
        if ride is not None:
            ride["cycles_since_inspection"] = 0
            if ride["license_status"] in ("PENDING", "SUSPENDED"):
                ride["license_status"] = "LICENSED"
            touch(ride)
    return ok(serialize(appointment))


@bp.post("/inspection-appointments/<aid>/cancel")
def cancel_appointment(aid):
    ctx = authenticate(["FairManager"])
    appointment = get_or_404("appointments", aid)
    scope_to_fair(ctx, appointment["fair_id"])
    body = get_body()
    reject_unknown(body, set())
    if appointment["status"] != "SCHEDULED":
        raise_err(ERR_APPOINTMENT_INVALID_STATE, "Only a SCHEDULED appointment can be cancelled")
    appointment["status"] = "CANCELLED"
    touch(appointment)
    return ok(serialize(appointment))
