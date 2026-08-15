"""Volunteers, certification, hours ledger (PRD 3.4)."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error, ERR_VALIDATION, ERR_INVALID_STATE, ERR_CONSTRAINT_VIOLATION,
    ERR_REFERENCE_INVALID, ERR_TEMPORAL_CONFLICT, ERR_CERTIFICATION_INSUFFICIENT,
    ERR_CANCEL_IN_LOCKOUT, ERR_NOT_FOUND, ERR_UNAUTHORIZED_ROLE,
)
from helpers import (
    get_body, req_field, req_enum, opt_enum, opt_field, stamp_new, paginate,
    apply_filters, get_or_404, touch,
)
from middleware import get_caller, check_role_allowed
from response import success_object, success_list
from routes.common import public, public_list
from services import core
from util import parse_datetime, fmt_datetime, CLOCK
from datetime import timedelta

bp = Blueprint("volunteers", __name__)

CERTS = {"NONE", "BASIC", "SUPERVISOR"}
SHIFT_ROLES = {"PREP", "COOK", "SERVER", "DRIVER", "SUPERVISOR_ON_DUTY"}
KM = ["KitchenManager"]


def _vol_view(v):
    out = public(v)
    out.pop("_certification_expires_at", None)
    return out


def _shift_view(s):
    out = public(s)
    out.pop("_starts_at", None)
    out.pop("_ends_at", None)
    return out


# ---------------------------------------------------------------------------
# Volunteer records
# ---------------------------------------------------------------------------

@bp.route("/kitchen/volunteers", methods=["POST"])
def create_volunteer():
    body = get_body()
    caller = get_caller()
    check_role_allowed(caller, ["ProgramAdmin", "KitchenManager"])

    full_name = req_field(body, "full_name", str)
    email = req_field(body, "email", str)
    cert_level = opt_enum(body, "certification_level", CERTS, "NONE")
    cert_expires = opt_field(body, "certification_expires_at", str, None, allow_null=True)

    exp_dt = None
    if cert_expires is not None:
        try:
            exp_dt = parse_datetime(cert_expires)
            cert_expires = fmt_datetime(exp_dt)
        except ValueError:
            raise_error(ERR_VALIDATION, "certification_expires_at must be an ISO datetime")

    for v in db["volunteers"].values():
        if v["email"] == email:
            raise_error(ERR_CONSTRAINT_VIOLATION, f"email already registered: {email}")

    rec = stamp_new({
        "full_name": full_name,
        "email": email,
        "certification_level": cert_level,
        "certification_expires_at": cert_expires,
        "_certification_expires_at": exp_dt,
        "hours_balance": 0,
        "strike_count": 0,
        "status": "ACTIVE",
    })
    db["volunteers"][rec["id"]] = rec
    return success_object(_vol_view(rec), 201)


@bp.route("/kitchen/volunteers", methods=["GET"])
def list_volunteers():
    caller = get_caller()
    check_role_allowed(caller, ["ProgramAdmin", "KitchenManager"])
    items = apply_filters(list(db["volunteers"].values()), request.args,
                          ["status", "certification_level"])
    page, total, limit, offset = paginate(items, request.args)
    return success_list([_vol_view(v) for v in page], total, limit, offset)


@bp.route("/kitchen/volunteers/<vid>", methods=["GET"])
def get_volunteer(vid):
    caller = get_caller()
    check_role_allowed(caller, ["ProgramAdmin", "KitchenManager", "Volunteer"])
    rec = get_or_404("volunteers", vid)
    return success_object(_vol_view(rec))


@bp.route("/kitchen/volunteers/<vid>/volunteer-shifts", methods=["GET"])
def list_volunteer_shifts(vid):
    caller = get_caller()
    check_role_allowed(caller, ["ProgramAdmin", "KitchenManager", "Volunteer"])
    get_or_404("volunteers", vid)
    items = [s for s in db["volunteer_shifts"].values() if s["volunteer_id"] == vid]
    items = apply_filters(items, request.args, ["status"])
    page, total, limit, offset = paginate(items, request.args)
    return success_list([_shift_view(s) for s in page], total, limit, offset)


@bp.route("/kitchen/volunteers/<vid>/suspend", methods=["POST"])
def suspend_volunteer(vid):
    get_body()
    caller = get_caller()
    check_role_allowed(caller, KM)
    v = get_or_404("volunteers", vid)
    if v["status"] != "ACTIVE":
        raise_error(ERR_INVALID_STATE, f"cannot suspend from {v['status']}")
    core.suspend_volunteer(v)
    return success_object(_vol_view(v))


@bp.route("/kitchen/volunteers/<vid>/reinstate", methods=["POST"])
def reinstate_volunteer(vid):
    get_body()
    caller = get_caller()
    check_role_allowed(caller, KM)
    v = get_or_404("volunteers", vid)
    if v["status"] != "SUSPENDED":
        raise_error(ERR_INVALID_STATE, f"cannot reinstate from {v['status']}")
    v["strike_count"] = 0
    v["status"] = "ACTIVE"
    touch(v)
    return success_object(_vol_view(v))


# ---------------------------------------------------------------------------
# Shifts
# ---------------------------------------------------------------------------

@bp.route("/kitchen/volunteer-shifts", methods=["POST"])
def create_shift():
    body = get_body()
    caller = get_caller()
    check_role_allowed(caller, KM)

    site_id = req_field(body, "site_id", str)
    volunteer_id = req_field(body, "volunteer_id", str)
    menu_day_id = req_field(body, "menu_day_id", str)
    role_on_shift = req_enum(body, "role_on_shift", SHIFT_ROLES)
    starts_at_s = req_field(body, "starts_at", str)
    ends_at_s = req_field(body, "ends_at", str)
    try:
        starts_at = parse_datetime(starts_at_s)
        ends_at = parse_datetime(ends_at_s)
    except ValueError:
        raise_error(ERR_VALIDATION, "starts_at and ends_at must be ISO datetimes")
    if ends_at <= starts_at:
        raise_error(ERR_VALIDATION, "ends_at must be after starts_at")

    if site_id not in db["sites"]:
        raise_error(ERR_REFERENCE_INVALID, f"site not found: {site_id}")
    volunteer = db["volunteers"].get(volunteer_id)
    if volunteer is None:
        raise_error(ERR_REFERENCE_INVALID, f"volunteer not found: {volunteer_id}")
    if volunteer["status"] != "ACTIVE":
        raise_error(ERR_REFERENCE_INVALID, f"volunteer is {volunteer['status']}")
    if menu_day_id not in db["menu_days"]:
        raise_error(ERR_REFERENCE_INVALID, f"menu day not found: {menu_day_id}")

    if not core.certification_valid(volunteer, role_on_shift):
        raise_error(ERR_CERTIFICATION_INSUFFICIENT,
                    f"certification insufficient for role {role_on_shift}")

    if core.volunteer_has_overlap(volunteer_id, starts_at, ends_at):
        raise_error(ERR_TEMPORAL_CONFLICT, "volunteer already has an overlapping shift")

    rec = stamp_new({
        "site_id": site_id,
        "volunteer_id": volunteer_id,
        "menu_day_id": menu_day_id,
        "role_on_shift": role_on_shift,
        "starts_at": fmt_datetime(starts_at),
        "ends_at": fmt_datetime(ends_at),
        "_starts_at": starts_at,
        "_ends_at": ends_at,
        "status": "SCHEDULED",
    })
    db["volunteer_shifts"][rec["id"]] = rec
    return success_object(_shift_view(rec), 201)


@bp.route("/kitchen/volunteer-shifts/<sid>", methods=["GET"])
def get_shift(sid):
    caller = get_caller()
    check_role_allowed(caller, ["ProgramAdmin", "KitchenManager", "Volunteer"])
    rec = get_or_404("volunteer_shifts", sid)
    _lazy_no_show(rec)
    return success_object(_shift_view(rec))


def _lazy_no_show(shift):
    """System auto-transition at ends_at when never checked in (lazy evaluation)."""
    if shift["status"] == "SCHEDULED" and CLOCK.now() >= shift["_ends_at"]:
        shift["status"] = "NO_SHOW"
        touch(shift)
        v = db["volunteers"].get(shift["volunteer_id"])
        if v is not None:
            core.apply_strike(v)


@bp.route("/kitchen/volunteer-shifts/<sid>/check-in", methods=["POST"])
def check_in(sid):
    get_body()
    caller = get_caller()
    check_role_allowed(caller, ["Volunteer"])
    shift = get_or_404("volunteer_shifts", sid)
    _lazy_no_show(shift)

    if shift["volunteer_id"] != caller.user_id:
        raise_error(ERR_UNAUTHORIZED_ROLE, "a volunteer may only check in to their own shift")

    if shift["status"] != "SCHEDULED":
        raise_error(ERR_INVALID_STATE, f"cannot check in from {shift['status']}")

    volunteer = db["volunteers"].get(shift["volunteer_id"])
    if volunteer is None or volunteer["status"] != "ACTIVE":
        raise_error(ERR_INVALID_STATE, "volunteer is not ACTIVE")

    if not core.certification_valid(volunteer, shift["role_on_shift"]):
        raise_error(ERR_CERTIFICATION_INSUFFICIENT,
                    "certification insufficient or expired for this role")

    now = CLOCK.now()
    window_open = shift["_starts_at"] - timedelta(minutes=15)
    if not (window_open <= now < shift["_ends_at"]):
        raise_error(ERR_TEMPORAL_CONFLICT, "outside the check-in window")

    shift["status"] = "CHECKED_IN"
    touch(shift)
    return success_object(_shift_view(shift))


@bp.route("/kitchen/volunteer-shifts/<sid>/complete", methods=["POST"])
def complete_shift(sid):
    body = get_body()
    caller = get_caller()
    check_role_allowed(caller, KM)
    shift = get_or_404("volunteer_shifts", sid)

    early_close = body.get("early_close", False)
    if not isinstance(early_close, bool):
        raise_error(ERR_VALIDATION, "early_close must be a boolean")

    if shift["status"] != "CHECKED_IN":
        raise_error(ERR_INVALID_STATE, f"cannot complete from {shift['status']}")

    if not early_close and CLOCK.now() < shift["_ends_at"]:
        raise_error(ERR_INVALID_STATE,
                    "shift may only be completed at or after ends_at, or with early_close")

    shift["status"] = "COMPLETED"
    touch(shift)
    volunteer = db["volunteers"].get(shift["volunteer_id"])
    if volunteer is not None:
        core.credit_hours(volunteer, shift)
    return success_object(_shift_view(shift))


@bp.route("/kitchen/volunteer-shifts/<sid>/reassign", methods=["POST"])
def reassign_shift(sid):
    body = get_body()
    caller = get_caller()
    check_role_allowed(caller, KM)
    shift = get_or_404("volunteer_shifts", sid)

    new_vid = req_field(body, "volunteer_id", str)

    if shift["status"] != "CHECKED_IN":
        raise_error(ERR_INVALID_STATE, f"cannot reassign from {shift['status']}")

    volunteer = db["volunteers"].get(new_vid)
    if volunteer is None:
        raise_error(ERR_REFERENCE_INVALID, f"volunteer not found: {new_vid}")
    if volunteer["status"] != "ACTIVE":
        raise_error(ERR_REFERENCE_INVALID, f"volunteer is {volunteer['status']}")

    if not core.certification_valid(volunteer, shift["role_on_shift"]):
        raise_error(ERR_CERTIFICATION_INSUFFICIENT,
                    "certification insufficient for the new assignee")
    if core.volunteer_has_overlap(new_vid, shift["_starts_at"], shift["_ends_at"],
                                  exclude_shift_id=shift["id"]):
        raise_error(ERR_TEMPORAL_CONFLICT, "new assignee has an overlapping shift")

    shift["volunteer_id"] = new_vid
    shift["status"] = "SCHEDULED"
    touch(shift)
    return success_object(_shift_view(shift))


@bp.route("/kitchen/volunteer-shifts/<sid>/cancel", methods=["POST"])
def cancel_shift(sid):
    body = get_body()
    caller = get_caller()
    check_role_allowed(caller, ["Volunteer", "KitchenManager"])
    shift = get_or_404("volunteer_shifts", sid)
    _lazy_no_show(shift)

    apply_penalty = body.get("apply_penalty", False)
    if not isinstance(apply_penalty, bool):
        raise_error(ERR_VALIDATION, "apply_penalty must be a boolean")

    if caller.role == "Volunteer" and shift["volunteer_id"] != caller.user_id:
        raise_error(ERR_UNAUTHORIZED_ROLE, "a volunteer may only cancel their own shift")

    if shift["status"] != "SCHEDULED":
        raise_error(ERR_INVALID_STATE, f"cannot cancel from {shift['status']}")

    now = CLOCK.now()
    lockout_boundary = shift["_starts_at"] - timedelta(hours=core.CANCEL_LOCKOUT_HOURS)
    inside_lockout = now >= lockout_boundary

    volunteer = db["volunteers"].get(shift["volunteer_id"])

    if caller.role == "Volunteer":
        if inside_lockout:
            raise_error(ERR_CANCEL_IN_LOCKOUT,
                        "self-cancel inside the lockout window is not permitted")
    else:  # KitchenManager
        if inside_lockout and apply_penalty and volunteer is not None:
            core.apply_penalty(volunteer)

    shift["status"] = "CANCELLED"
    touch(shift)
    return success_object(_shift_view(shift))


@bp.route("/kitchen/volunteer-shifts/<sid>/mark-no-show", methods=["POST"])
def mark_no_show(sid):
    get_body()
    caller = get_caller()
    check_role_allowed(caller, KM)
    shift = get_or_404("volunteer_shifts", sid)

    if shift["status"] != "SCHEDULED":
        raise_error(ERR_INVALID_STATE, f"cannot mark no-show from {shift['status']}")

    shift["status"] = "NO_SHOW"
    touch(shift)
    v = db["volunteers"].get(shift["volunteer_id"])
    if v is not None:
        core.apply_strike(v)
    return success_object(_shift_view(shift))
