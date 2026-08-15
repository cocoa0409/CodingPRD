from datetime import datetime, time, timedelta, timezone

from flask import Blueprint, request

import db
from errors import (
    ERR_INVALID_DATE_RANGE,
    ERR_INVALID_NURSE_STATE,
    ERR_INVALID_SHIFT_STATE,
    ERR_NOT_FOUND,
    ERR_NURSE_NOT_CLEAR,
    ERR_NURSE_NOT_FOUND,
    ERR_SCHEDULING_HORIZON_EXCEEDED,
    ERR_SHIFT_IN_PAST,
    ERR_SHIFT_NOT_STARTABLE,
    ERR_SHIFT_OVERLAP,
    ERR_UNIT_CERT_REQUIREMENT_UNMET,
    ERR_UNIT_NOT_FOUND,
    ERR_WEEKLY_HOURS_EXCEEDED,
    ApiError,
)
from middleware import auth_context, get_body, pagination_params, require_role, validate_body
from response import success_list, success_object
from services.core import all_entities, create_entity, get_or_404, serialize, touch
from services.derived import (
    SCHEDULING_HORIZON_DAYS,
    WEEKLY_HOUR_CAP_MINUTES,
    recompute_posture,
    unit_decrement,
    unit_increment,
)
from util import hours_display, minutes_between, parse_time_loose

bp = Blueprint("shifts", __name__)

CREATE_SCHEMA = {
    "nurse_id": ("string", True, None),
    "unit_id": ("string", True, None),
    "starts_at": ("datetime", True, None),
    "ends_at": ("datetime", True, None),
}


def _midnight_utc(d):
    return datetime.combine(d, time.min, tzinfo=timezone.utc)


@bp.route("/credentialing/shift-assignments", methods=["POST"])
def create_shift():
    user_id, role = auth_context()
    require_role(role, {"NurseManager"})
    body = validate_body(get_body(), CREATE_SCHEMA)
    nurse = get_or_404("nurses", body["nurse_id"], ERR_NURSE_NOT_FOUND, "nurse_id does not reference an existing nurse")
    unit = get_or_404("units", body["unit_id"], ERR_UNIT_NOT_FOUND, "unit_id does not reference an existing unit")
    starts_at = body["starts_at"]
    ends_at = body["ends_at"]
    # State gates on the related nurse (stage 7).
    if nurse["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_NURSE_STATE, "Shift creation requires an ACTIVE nurse", 409)
    if nurse["credential_posture"] != "CLEAR":
        raise ApiError(ERR_NURSE_NOT_CLEAR, "Shift creation requires a CLEAR credential posture", 409)
    # Safety (stage 8): unit certification prerequisites.
    for cert_type in unit["required_cert_types"]:
        if not any(
            c for c in all_entities("certifications")
            if c["nurse_id"] == nurse["id"] and c["cert_type"] == cert_type and c["status"] == "ACTIVE"
        ):
            raise ApiError(ERR_UNIT_CERT_REQUIREMENT_UNMET, f"Nurse lacks an ACTIVE {cert_type} certification required by the unit", 403)
    # Constraint (stage 9): half-open overlap among SCHEDULED / IN_PROGRESS.
    for existing in all_entities("shifts"):
        if existing["nurse_id"] != nurse["id"] or existing["status"] not in ("SCHEDULED", "IN_PROGRESS"):
            continue
        e_start = parse_time_loose(existing["starts_at"])
        e_end = parse_time_loose(existing["ends_at"])
        if starts_at < e_end and e_start < ends_at:
            raise ApiError(ERR_SHIFT_OVERLAP, "New shift collides with an existing assignment", 409)
    # Temporal (stage 10): date range, then past, then horizon.
    today = db.current_date()
    if ends_at <= starts_at:
        raise ApiError(ERR_INVALID_DATE_RANGE, "ends_at must be strictly after starts_at", 422)
    start_date = starts_at.date()
    if start_date < today:
        raise ApiError(ERR_SHIFT_IN_PAST, "Shift start date precedes the current date", 422)
    if start_date > today + timedelta(days=SCHEDULING_HORIZON_DAYS):
        raise ApiError(ERR_SCHEDULING_HORIZON_EXCEEDED, "Shift start date lies beyond the 90-day scheduling horizon", 422)
    # Labor budget (stage 11): rolling 7-calendar-day window, integer minutes.
    window_start = _midnight_utc(start_date) - timedelta(days=6)
    window_end = _midnight_utc(start_date) + timedelta(days=1)
    total_minutes = minutes_between(starts_at, ends_at)
    for existing in all_entities("shifts"):
        if existing["nurse_id"] != nurse["id"] or existing["status"] not in ("SCHEDULED", "IN_PROGRESS", "COMPLETED"):
            continue
        e_start = parse_time_loose(existing["starts_at"])
        e_end = parse_time_loose(existing["ends_at"])
        if e_start < window_end and window_start < e_end:
            total_minutes += minutes_between(e_start, e_end)
    if total_minutes > WEEKLY_HOUR_CAP_MINUTES:
        raise ApiError(ERR_WEEKLY_HOURS_EXCEEDED, "Weekly 60-hour cap exceeded for the assignment's 7-day window", 422)
    minutes = minutes_between(starts_at, ends_at)
    shift = create_entity("shifts", {
        "nurse_id": nurse["id"],
        "unit_id": unit["id"],
        "starts_at": starts_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "ends_at": ends_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "hours": hours_display(minutes),
        "status": "SCHEDULED",
        "was_clear_at_start": None,
        "cancel_reason": None,
    })
    unit_increment(unit, shift["hours"])
    recompute_posture(nurse)
    return success_object(serialize("shifts", shift), 201)


@bp.route("/credentialing/shift-assignments", methods=["GET"])
def list_shifts():
    auth_context()
    limit, offset = pagination_params()
    rows = all_entities("shifts")
    for param in ("nurse_id", "unit_id", "status"):
        value = request.args.get(param)
        if value is not None:
            rows = [s for s in rows if s[param] == value]
    total = len(rows)
    return success_list([serialize("shifts", s) for s in rows[offset:offset + limit]], limit, offset, total)


@bp.route("/credentialing/shift-assignments/<shiftId>", methods=["GET"])
def get_shift(shiftId):
    auth_context()
    shift = get_or_404("shifts", shiftId, ERR_NOT_FOUND, "Shift assignment not found")
    return success_object(serialize("shifts", shift))


@bp.route("/credentialing/shift-assignments/<shiftId>/start", methods=["POST"])
def start_shift(shiftId):
    user_id, role = auth_context()
    require_role(role, {"NurseManager"})
    shift = get_or_404("shifts", shiftId, ERR_NOT_FOUND, "Shift assignment not found")
    if shift["status"] != "SCHEDULED":
        raise ApiError(ERR_INVALID_SHIFT_STATE, "Only a SCHEDULED assignment can be started", 409)
    now = db.logical_now()
    if not (parse_time_loose(shift["starts_at"]) <= now < parse_time_loose(shift["ends_at"])):
        raise ApiError(ERR_SHIFT_NOT_STARTABLE, "Current instant is outside the shift's [starts_at, ends_at) window", 422)
    nurse = db.STORES["nurses"].get(shift["nurse_id"])
    if nurse is None or nurse["credential_posture"] != "CLEAR":
        raise ApiError(ERR_NURSE_NOT_CLEAR, "Shift start requires a CLEAR credential posture", 409)
    shift["status"] = "IN_PROGRESS"
    shift["was_clear_at_start"] = True
    touch(shift)
    return success_object(serialize("shifts", shift))


@bp.route("/credentialing/shift-assignments/<shiftId>/complete", methods=["POST"])
def complete_shift(shiftId):
    user_id, role = auth_context()
    require_role(role, {"NurseManager"})
    shift = get_or_404("shifts", shiftId, ERR_NOT_FOUND, "Shift assignment not found")
    if shift["status"] != "IN_PROGRESS":
        raise ApiError(ERR_INVALID_SHIFT_STATE, "Only an IN_PROGRESS assignment can be completed", 409)
    shift["status"] = "COMPLETED"
    touch(shift)
    # Completed assignments leave the {SCHEDULED, IN_PROGRESS} counter set.
    unit_decrement(db.STORES["units"].get(shift["unit_id"]), shift["hours"])
    return success_object(serialize("shifts", shift))


@bp.route("/credentialing/shift-assignments/<shiftId>/cancel", methods=["POST"])
def cancel_shift(shiftId):
    user_id, role = auth_context()
    require_role(role, {"NurseManager"})
    shift = get_or_404("shifts", shiftId, ERR_NOT_FOUND, "Shift assignment not found")
    if shift["status"] != "SCHEDULED":
        raise ApiError(ERR_INVALID_SHIFT_STATE, "Only a SCHEDULED assignment can be cancelled", 409)
    shift["status"] = "CANCELLED"
    shift["cancel_reason"] = "MANUAL"
    touch(shift)
    unit_decrement(db.STORES["units"].get(shift["unit_id"]), shift["hours"])
    nurse = db.STORES["nurses"].get(shift["nurse_id"])
    if nurse is not None:
        recompute_posture(nurse)
    return success_object(serialize("shifts", shift))
