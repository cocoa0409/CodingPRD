"""Crew shifts: schedule (OCC on staff version, half-open overlap, season window),
read, list, confirm, complete, no-show, cancel."""
from flask import Blueprint

import db
from db import store, serialize, touch
from errors import (
    raise_err,
    ERR_INVALID_REQUEST,
    ERR_STAFF_INVALID_STATE,
    ERR_STALE_STAFF_VERSION,
    ERR_STAFF_SHIFT_OVERLAP,
    ERR_SHIFT_OUT_OF_SEASON,
    ERR_SHIFT_INVALID_STATE,
)
from helpers import get_or_404, paginate, qparam, shift_season_window
from middleware import authenticate, scope_to_fair, require_owner
from response import ok
from validators import get_body, reject_unknown, req_str, req_int, req_enum, req_date

bp = Blueprint("shifts", __name__)

ALL = ["StateProgramAdmin", "StateInspector", "FairManager", "RideOperator", "TicketClerk", "CrewMember"]

SHIFT_ROLES = ["SETUP", "OPERATIONS", "TEARDOWN"]


@bp.post("/crew-shifts")
def create_shift():
    ctx = authenticate(["FairManager"])
    body = get_body()
    reject_unknown(
        body,
        {"staff_id", "work_date", "start_hour", "end_hour", "shift_role", "expected_staff_version"},
    )
    staff_id = req_str(body, "staff_id")
    work_date_str = req_str(body, "work_date")
    work_date = req_date(body, "work_date")
    start_hour = req_int(body, "start_hour", lo=0, hi=23)
    end_hour = req_int(body, "end_hour", lo=1, hi=24)
    shift_role = req_enum(body, "shift_role", SHIFT_ROLES)
    expected_version = req_int(body, "expected_staff_version")
    if start_hour >= end_hour:
        raise_err(ERR_INVALID_REQUEST, "start_hour must precede end_hour")
    if end_hour - start_hour > 12:
        raise_err(ERR_INVALID_REQUEST, "A shift may not exceed twelve hours")
    staff = db.get("staff", staff_id)
    scope_to_fair(ctx, staff["fair_id"] if staff else None)
    staff = get_or_404("staff", staff_id)
    scope_to_fair(ctx, staff["fair_id"])
    if "CREW" not in staff.get("functions", []):
        raise_err(ERR_INVALID_REQUEST, "The staff member must carry the CREW function")
    if staff["status"] != "ACTIVE":
        raise_err(ERR_STAFF_INVALID_STATE, "The staff member is RELEASED")
    if expected_version != staff["version"]:
        raise_err(ERR_STALE_STAFF_VERSION, "expected_staff_version does not match the staff member's current version")
    for existing in store["shifts"].values():
        if (
            existing["staff_id"] == staff_id
            and existing["work_date"] == work_date_str
            and existing["status"] in ("SCHEDULED", "CONFIRMED", "COMPLETED")
            and start_hour < existing["end_hour"]
            and existing["start_hour"] < end_hour
        ):
            raise_err(ERR_STAFF_SHIFT_OVERLAP, "The shift overlaps an existing shift for this staff member and date")
    fair = db.get("fairs", staff["fair_id"])
    window_start, window_end = shift_season_window(fair, shift_role)
    if work_date < db.today_date() or not (window_start <= work_date <= window_end):
        raise_err(ERR_SHIFT_OUT_OF_SEASON, "work_date is in the past or outside the shift role's season window")
    shift = db.register(
        "shifts",
        {
            "staff_id": staff_id,
            "fair_id": staff["fair_id"],
            "work_date": work_date_str,
            "start_hour": start_hour,
            "end_hour": end_hour,
            "shift_role": shift_role,
            "status": "SCHEDULED",
        },
    )
    touch(staff)  # booking a shift mutates the staff ledger
    return ok(serialize(shift), 201)


@bp.get("/crew-shifts/<sid>")
def get_shift(sid):
    ctx = authenticate(ALL)
    shift = get_or_404("shifts", sid)
    scope_to_fair(ctx, shift["fair_id"])
    return ok(serialize(shift))


@bp.get("/crew-shifts")
def list_shifts():
    authenticate(ALL)
    return paginate(
        "shifts",
        {
            "staff_id": qparam("staff_id"),
            "fair_id": qparam("fair_id"),
            "work_date": qparam("work_date"),
            "shift_role": qparam("shift_role"),
            "status": qparam("status"),
        },
    )


@bp.post("/crew-shifts/<sid>/confirm")
def confirm_shift(sid):
    ctx = authenticate(["CrewMember"])
    shift = get_or_404("shifts", sid)
    scope_to_fair(ctx, shift["fair_id"])
    require_owner(ctx["user_id"] == shift["staff_id"])
    body = get_body()
    reject_unknown(body, set())
    if shift["status"] != "SCHEDULED":
        raise_err(ERR_SHIFT_INVALID_STATE, "Only a SCHEDULED shift can be confirmed")
    if shift["work_date"] < db.today_str():
        raise_err(ERR_SHIFT_OUT_OF_SEASON, "The shift's work date has already passed")
    shift["status"] = "CONFIRMED"
    touch(shift)
    return ok(serialize(shift))


@bp.post("/crew-shifts/<sid>/complete")
def complete_shift(sid):
    ctx = authenticate(["FairManager"])
    shift = get_or_404("shifts", sid)
    scope_to_fair(ctx, shift["fair_id"])
    body = get_body()
    reject_unknown(body, set())
    if shift["status"] != "CONFIRMED":
        raise_err(ERR_SHIFT_INVALID_STATE, "Only a CONFIRMED shift can be completed")
    if shift["work_date"] > db.today_str():
        raise_err(ERR_SHIFT_OUT_OF_SEASON, "The shift's work date has not arrived")
    shift["status"] = "COMPLETED"
    touch(shift)
    return ok(serialize(shift))


@bp.post("/crew-shifts/<sid>/no-show")
def no_show_shift(sid):
    ctx = authenticate(["FairManager"])
    shift = get_or_404("shifts", sid)
    scope_to_fair(ctx, shift["fair_id"])
    body = get_body()
    reject_unknown(body, set())
    if shift["status"] not in ("SCHEDULED", "CONFIRMED"):
        raise_err(ERR_SHIFT_INVALID_STATE, "Only a SCHEDULED or CONFIRMED shift can be marked NO_SHOW")
    if shift["work_date"] > db.today_str():
        raise_err(ERR_SHIFT_OUT_OF_SEASON, "The shift's work date has not arrived")
    shift["status"] = "NO_SHOW"
    touch(shift)
    return ok(serialize(shift))


@bp.post("/crew-shifts/<sid>/cancel")
def cancel_shift(sid):
    ctx = authenticate(["FairManager"])
    shift = get_or_404("shifts", sid)
    scope_to_fair(ctx, shift["fair_id"])
    body = get_body()
    reject_unknown(body, set())
    if shift["status"] not in ("SCHEDULED", "CONFIRMED"):
        raise_err(ERR_SHIFT_INVALID_STATE, "Only a SCHEDULED or CONFIRMED shift can be cancelled")
    shift["status"] = "CANCELLED"
    touch(shift)
    return ok(serialize(shift))
