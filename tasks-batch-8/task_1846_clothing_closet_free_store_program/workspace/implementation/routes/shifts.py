"""Volunteer shifts and signups (PRD 3.7)."""
from flask import Blueprint, g

import db
import services as svc
from db import stamp_new, store, touch
from errors import ApiError, forbidden, invalid_state, not_found
from middleware import require_roles
from response import ok, ok_list
from routes.volunteers import SIGNUP_STATUSES, get_volunteer_or_404
from util import (
    get_body, opt_enum_filter, page_params, paginate, v_dt, v_enum, v_int,
)

bp = Blueprint("shifts", __name__)

ROLE_TYPES = {"SORTING", "INTAKE", "FLOOR"}


def get_shift_or_404(shift_id):
    s = store.shifts.get(shift_id)
    if s is None:
        raise not_found("Volunteer shift not found")
    return s


def get_signup_or_404(shift, signup_id):
    s = store.signups.get(signup_id)
    if s is None or s["shift_id"] != shift["id"]:
        raise not_found("Shift signup not found")
    return s


def _check_signup_ownership(signup):
    """A Volunteer may act only on their own signup; leads/admins on any."""
    if g.user_role == "Volunteer" and signup["volunteer_id"] != g.user_id:
        raise forbidden("Volunteers may only act on their own signups")


@bp.post("/closet/shifts")
@require_roles("ProgramAdmin", "VolunteerLead")
def create_shift():
    data = get_body()
    start_at = v_dt(data, "start_at")
    end_at = v_dt(data, "end_at")
    role_type = v_enum(data, "role_type", ROLE_TYPES)
    capacity = v_int(data, "capacity_volunteers", lo=1)
    if not end_at > start_at:
        raise ApiError("ERR_INVALID_REQUEST", 400, "end_at must be after start_at")
    s = stamp_new({
        "start_at": start_at,
        "end_at": end_at,
        "role_type": role_type,
        "capacity_volunteers": capacity,
        "status": "OPEN",
    })
    store.shifts[s["id"]] = s
    return ok(svc.serialize_shift(s), 201)


@bp.get("/closet/shifts/<sid>")
@require_roles("ProgramAdmin", "VolunteerLead", "Volunteer")
def get_shift(sid):
    return ok(svc.serialize_shift(get_shift_or_404(sid)))


@bp.post("/closet/shifts/<sid>/cancel")
@require_roles("ProgramAdmin", "VolunteerLead")
def cancel_shift(sid):
    shift = get_shift_or_404(sid)
    if shift["status"] not in ("OPEN", "LOCKED"):
        raise invalid_state("Only an OPEN or LOCKED shift can be cancelled")
    for signup in store.signups.values():
        if signup["shift_id"] == sid and signup["status"] in ("SIGNED_UP", "CHECKED_IN"):
            signup["status"] = "CANCELLED"
            touch(signup)
    shift["status"] = "CANCELLED"
    touch(shift)
    return ok(svc.serialize_shift(shift))


@bp.post("/closet/shifts/<sid>/complete")
@require_roles("ProgramAdmin", "VolunteerLead")
def complete_shift(sid):
    shift = get_shift_or_404(sid)
    if shift["status"] not in ("OPEN", "LOCKED"):
        raise invalid_state("Only an OPEN or LOCKED shift can be completed")
    if db.now() < shift["end_at"]:
        raise ApiError(
            "ERR_SHIFT_NOT_IN_WINDOW", 409,
            "A shift can only complete at or after its end_at",
        )
    for signup in store.signups.values():
        if signup["shift_id"] != sid:
            continue
        if signup["status"] == "SIGNED_UP":
            signup["status"] = "NO_SHOW"
            touch(signup)
        elif signup["status"] == "CHECKED_IN":
            signup["status"] = "COMPLETED"
            touch(signup)
    shift["status"] = "COMPLETED"
    touch(shift)
    return ok(svc.serialize_shift(shift))


@bp.post("/closet/shifts/<sid>/signups")
@require_roles("ProgramAdmin", "VolunteerLead", "Volunteer")
def create_signup(sid):
    shift = get_shift_or_404(sid)
    data = get_body()
    volunteer_id = data.get("volunteer_id")
    if volunteer_id is None:
        raise ApiError(
            "ERR_INVALID_REQUEST", 400, "Missing required field: volunteer_id"
        )
    if not isinstance(volunteer_id, str):
        raise ApiError("ERR_INVALID_REQUEST", 400, "volunteer_id must be a string")
    get_volunteer_or_404(volunteer_id)

    if shift["status"] in ("COMPLETED", "CANCELLED"):
        raise invalid_state("Cannot sign up for a COMPLETED or CANCELLED shift")
    if shift["status"] == "LOCKED":
        raise ApiError("ERR_SHIFT_FULL", 409, "Shift is at capacity")

    # Overlap: half-open intervals, back-to-back allowed. The same-shift case
    # is handled by the dedicated ERR_ALREADY_SIGNED_UP rule below.
    active_elsewhere = [
        s for s in store.signups.values()
        if s["volunteer_id"] == volunteer_id
        and s["status"] in ("SIGNED_UP", "CHECKED_IN")
        and s["shift_id"] != sid
    ]
    for other in active_elsewhere:
        other_shift = store.shifts.get(other["shift_id"])
        if other_shift is None:
            continue
        if other_shift["start_at"] < shift["end_at"] and shift["start_at"] < other_shift["end_at"]:
            raise ApiError(
                "ERR_SHIFT_OVERLAP", 409,
                "Volunteer holds an active signup on an overlapping shift",
            )
    if any(
        s["volunteer_id"] == volunteer_id
        and s["status"] in ("SIGNED_UP", "CHECKED_IN")
        and s["shift_id"] == sid
        for s in store.signups.values()
    ):
        raise ApiError(
            "ERR_ALREADY_SIGNED_UP", 409,
            "Volunteer already has an active signup on this shift",
        )

    signup = stamp_new({
        "shift_id": sid,
        "volunteer_id": volunteer_id,
        "status": "SIGNED_UP",
        "checked_in_at": None,
    })
    store.signups[signup["id"]] = signup
    # Auto-lock at capacity.
    if (
        shift["status"] == "OPEN"
        and svc.shift_active_signup_count(sid) >= shift["capacity_volunteers"]
    ):
        shift["status"] = "LOCKED"
        touch(shift)
    return ok(svc.serialize_signup(signup), 201)


@bp.get("/closet/shifts/<sid>/signups")
@require_roles("ProgramAdmin", "VolunteerLead", "Volunteer")
def list_shift_signups(sid):
    get_shift_or_404(sid)
    status = opt_enum_filter("status", SIGNUP_STATUSES)
    limit, offset = page_params()
    rows = [s for s in store.signups.values() if s["shift_id"] == sid]
    if status is not None:
        rows = [s for s in rows if s["status"] == status]
    page, total = paginate(rows, limit, offset)
    return ok_list([svc.serialize_signup(s) for s in page], total, limit, offset)


@bp.post("/closet/shifts/<sid>/signups/<upid>/cancel")
@require_roles("ProgramAdmin", "VolunteerLead", "Volunteer")
def cancel_signup(sid, upid):
    shift = get_shift_or_404(sid)
    signup = get_signup_or_404(shift, upid)
    _check_signup_ownership(signup)
    if signup["status"] != "SIGNED_UP":
        raise invalid_state("Only a SIGNED_UP signup can be cancelled")
    signup["status"] = "CANCELLED"
    touch(signup)
    # A LOCKED shift reopens when it drops back below capacity.
    if (
        shift["status"] == "LOCKED"
        and svc.shift_active_signup_count(sid) < shift["capacity_volunteers"]
    ):
        shift["status"] = "OPEN"
        touch(shift)
    return ok(svc.serialize_signup(signup))


@bp.post("/closet/shifts/<sid>/signups/<upid>/check-in")
@require_roles("ProgramAdmin", "VolunteerLead", "Volunteer")
def check_in_signup(sid, upid):
    shift = get_shift_or_404(sid)
    signup = get_signup_or_404(shift, upid)
    _check_signup_ownership(signup)
    if signup["status"] != "SIGNED_UP":
        raise invalid_state("Only a SIGNED_UP signup can be checked in")
    now = db.now()
    if (
        shift["status"] not in ("OPEN", "LOCKED")
        or not (shift["start_at"] <= now <= shift["end_at"])
    ):
        raise ApiError(
            "ERR_SHIFT_NOT_IN_WINDOW", 409,
            "Check-in is only allowed inside [start_at, end_at] on an "
            "OPEN or LOCKED shift",
        )
    signup["status"] = "CHECKED_IN"
    signup["checked_in_at"] = now
    touch(signup)
    return ok(svc.serialize_signup(signup))
