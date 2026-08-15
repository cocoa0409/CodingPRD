"""Volunteer shifts: scheduling, check-in, completion, cancel (PRD §3.6)."""

from datetime import timedelta

from flask import Blueprint, request

from db import db, _parse_iso
from errors import ApiError
from middleware import require_roles, get_body, validate_payload
from response import success
from services.core import make_common, touch, paginate, sorted_by_created, MAX_SHIFT_MINUTES

bp = Blueprint("shifts", __name__)

SHIFT_ROLES = ["MECHANIC", "INTAKE", "FLOOR"]


def shift_view(s):
    return {
        "id": s["id"],
        "volunteer_id": s["volunteer_id"],
        "shift_role": s["shift_role"],
        "scheduled_start": s["scheduled_start"],
        "scheduled_end": s["scheduled_end"],
        "status": s["status"],
        "checked_in_at": s["checked_in_at"],
        "credited_minutes": s["credited_minutes"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def _get_shift(shift_id):
    shift = db.shifts.get(shift_id)
    if shift is None:
        raise ApiError("ERR_NOT_FOUND", f"VolunteerShift {shift_id} does not exist")
    return shift


@bp.post("/shifts")
def create_shift():
    require_roles("ShopCoordinator")
    body = get_body()
    validate_payload(body, {
        "volunteer_id": {"type": "string", "required": True},
        "shift_role": {"type": "string", "required": True, "enum": SHIFT_ROLES},
        "scheduled_start": {"type": "string", "required": True},
        "scheduled_end": {"type": "string", "required": True},
    })
    vol = db.volunteers.get(body["volunteer_id"])
    if vol is None:
        raise ApiError("ERR_NOT_FOUND", f"Volunteer {body['volunteer_id']} does not exist")
    try:
        start = _parse_iso(body["scheduled_start"])
        end = _parse_iso(body["scheduled_end"])
    except (ValueError, TypeError):
        raise ApiError("ERR_VALIDATION", "scheduled_start/scheduled_end must be ISO-8601 instants")
    if vol["engagement_status"] != "ACTIVE":
        raise ApiError("ERR_VOLUNTEER_SUSPENDED", "Suspended volunteers cannot be scheduled")
    duration_min = (end - start).total_seconds() / 60
    if duration_min < 30 or duration_min > 480:
        raise ApiError("ERR_SHIFT_DURATION_INVALID", "Shift duration must be 30..480 minutes")
    # Half-open overlap: [start, end) must not intersect any existing
    # SCHEDULED/CHECKED_IN shift of this volunteer; touching endpoints are allowed.
    for other in db.shifts.values():
        if other["volunteer_id"] != vol["id"] or other["status"] not in ("SCHEDULED", "CHECKED_IN"):
            continue
        o_start = _parse_iso(other["scheduled_start"])
        o_end = _parse_iso(other["scheduled_end"])
        if start < o_end and o_start < end:
            raise ApiError("ERR_SHIFT_OVERLAP", "Shift overlaps an existing shift of this volunteer")

    shift = make_common()
    shift.update({
        "volunteer_id": vol["id"],
        "shift_role": body["shift_role"],
        "scheduled_start": body["scheduled_start"],
        "scheduled_end": body["scheduled_end"],
        "status": "SCHEDULED",
        "checked_in_at": None,
        "credited_minutes": None,
    })
    db.shifts[shift["id"]] = shift
    return success(shift_view(shift), status=201)


@bp.get("/shifts/<shift_id>")
def get_shift(shift_id):
    require_roles("ShopCoordinator", "ProgramDirector", "Volunteer")
    return success(shift_view(_get_shift(shift_id)))


@bp.get("/shifts")
def list_shifts():
    require_roles("ShopCoordinator", "ProgramDirector", "Volunteer")
    rows = list(db.shifts.values())
    for param in ("volunteer_id", "status"):
        value = request.args.get(param)
        if value is not None:
            rows = [s for s in rows if s[param] == value]
    rows = sorted_by_created(rows)
    page, pg = paginate(rows)
    return success([shift_view(s) for s in page], pagination=pg)


@bp.post("/shifts/<shift_id>/check-in")
def check_in_shift(shift_id):
    user_id, _ = require_roles("Volunteer")
    shift = _get_shift(shift_id)
    vol = db.volunteers.get(user_id)
    if vol is None:
        raise ApiError("ERR_NOT_FOUND", f"Volunteer {user_id} does not exist")
    if shift["volunteer_id"] != user_id:
        raise ApiError("ERR_NOT_YOUR_SHIFT", "Volunteers can only check in to their own shifts")
    if shift["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", "Only a SCHEDULED shift can be checked in")
    if vol["engagement_status"] != "ACTIVE":
        raise ApiError("ERR_VOLUNTEER_SUSPENDED", "Suspended volunteers cannot check in")
    now = db.now()
    start = _parse_iso(shift["scheduled_start"])
    end = _parse_iso(shift["scheduled_end"])
    if not (start - timedelta(minutes=15) <= now <= end):
        raise ApiError("ERR_CHECKIN_WINDOW_CLOSED", "Outside the check-in window")
    shift["status"] = "CHECKED_IN"
    shift["checked_in_at"] = db.now_iso()
    touch(shift)
    return success(shift_view(shift))


@bp.post("/shifts/<shift_id>/complete")
def complete_shift(shift_id):
    require_roles("ShopCoordinator")
    shift = _get_shift(shift_id)
    if shift["status"] != "CHECKED_IN":
        raise ApiError("ERR_INVALID_STATE", "Only a CHECKED_IN shift can be completed")
    start = _parse_iso(shift["scheduled_start"])
    end = _parse_iso(shift["scheduled_end"])
    credited = min(MAX_SHIFT_MINUTES, int((end - start).total_seconds() // 60))
    shift["credited_minutes"] = credited
    shift["status"] = "COMPLETED"
    touch(shift)
    vol = db.volunteers.get(shift["volunteer_id"])
    if vol is not None:
        vol["shift_minutes"] += credited
        touch(vol)
    return success(shift_view(shift))


@bp.post("/shifts/<shift_id>/cancel")
def cancel_shift(shift_id):
    user_id, role = require_roles("ShopCoordinator", "Volunteer")
    shift = _get_shift(shift_id)
    if role == "Volunteer" and shift["volunteer_id"] != user_id:
        raise ApiError("ERR_NOT_YOUR_SHIFT", "Volunteers can only cancel their own shifts")
    if shift["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", "Only a SCHEDULED shift can be cancelled")
    shift["status"] = "CANCELLED"
    touch(shift)
    return success(shift_view(shift))
