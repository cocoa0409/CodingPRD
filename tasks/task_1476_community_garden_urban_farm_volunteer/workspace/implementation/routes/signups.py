"""Shift signups: create, confirm (with waitlist branch), cancel, check-in/out.

Create-time gate order follows PRD section 3.5 (a refining section):
slot state -> lock window -> participation gates -> produce-safety cert ->
youth supervision -> duplicate signup.
"""
from datetime import timedelta

from flask import Blueprint, request

import clock
import db
import services
from app_util import body
from errors import err, err_not_found, err_ownership, err_state
from middleware import ALL_ROLES, require_auth, require_role
from response import ok
from util import pagination_args, require_field

bp = Blueprint("signups", __name__)

FOUR = ["GardenAdmin", "Coordinator", "Volunteer", "GroupLeader"]
STAFF = ["GardenAdmin", "Coordinator"]


def _get_slot(slot_id):
    slot = db.slots.get(slot_id)
    if slot is None:
        raise err_not_found("slot")
    return slot


def _get_signup(signup_id):
    signup = db.signups.get(signup_id)
    if signup is None:
        raise err_not_found("signup")
    return signup


def _check_participation_gates(vol):
    """PRD section 2.8 sub-order: orientation -> waiver -> not suspended."""
    if vol["orientation_status"] != "ORIENTED":
        raise err("ERR_ORIENTATION_REQUIRED", "volunteer orientation_status is not ORIENTED")
    if vol["waiver_status"] != "SIGNED":
        raise err("ERR_WAIVER_REQUIRED", "volunteer waiver_status is not SIGNED")
    if vol["standing"] == "SUSPENDED":
        raise err("ERR_VOLUNTEER_SUSPENDED", "volunteer is SUSPENDED")


def _check_supervision(slot_id: str, supervision_signup_id):
    """A minor's supervising signup must be on the same slot, CONFIRMED/CHECKED_IN,
    and its volunteer must hold an ACTIVE SUPERVISION cert."""
    if supervision_signup_id is None:
        raise err("ERR_YOUTH_SUPERVISION_REQUIRED", "minor signup requires supervision_adult_signup_id")
    adult = db.signups.get(supervision_signup_id)
    if (adult is None
            or adult["slot_id"] != slot_id
            or adult["status"] not in {"CONFIRMED", "CHECKED_IN"}
            or not services.has_active_cert(adult["volunteer_id"], "SUPERVISION")):
        raise err("ERR_YOUTH_SUPERVISION_REQUIRED",
                  "supervision adult signup is not a CONFIRMED/CHECKED_IN signup on this slot held by a can_supervise volunteer")


def _check_slot_lock(slot):
    if not (clock.now() < slot["starts_at"] - timedelta(hours=24)):
        raise err("ERR_SLOT_LOCKED", "slot is locked (within 24h of start)")


@bp.post("/api/shift-signups")
def create_signup():
    ctx = require_auth()
    require_role(ctx, FOUR)
    data = body()
    # existence (tier 3): slot_id, volunteer_id, supervision_adult_signup_id
    slot_id = require_field(data, "slot_id")
    slot = _get_slot(slot_id)
    volunteer_id = require_field(data, "volunteer_id")
    vol = db.volunteers.get(volunteer_id)
    if vol is None:
        raise err_not_found("volunteer")
    supervision_id = data.get("supervision_adult_signup_id")
    if supervision_id is not None and db.signups.get(supervision_id) is None:
        raise err_not_found("signup")
    # ownership (tier 4)
    if ctx.role in {"Volunteer", "GroupLeader"} and ctx.user_id != volunteer_id:
        raise err_ownership()
    # --- PRD 3.5 workflow gate sequence ---
    # 1. slot must be OPEN or FULL
    if slot["status"] not in {"OPEN", "FULL"}:
        raise err_state("SLOT")
    # 2. lock window
    _check_slot_lock(slot)
    # 3-5. participation gates
    _check_participation_gates(vol)
    # 6. produce-safety cert gate
    if slot["requires_produce_safety"] and not services.has_active_cert(volunteer_id, "PRODUCE_SAFETY"):
        raise err("ERR_PRODUCE_SAFETY_CERT_REQUIRED",
                  "slot requires an ACTIVE PRODUCE_SAFETY certification")
    # 7. youth supervision
    is_youth = services.volunteer_is_minor(vol)
    if is_youth:
        _check_supervision(slot_id, supervision_id)
    # 8. one non-terminal signup per volunteer per slot
    if any(s["slot_id"] == slot_id and s["volunteer_id"] == volunteer_id
           and s["status"] not in services.SIGNUP_TERMINAL
           for s in db.signups.values()):
        raise err("ERR_DUPLICATE_SIGNUP", "volunteer already has a non-terminal signup on this slot")
    rec = services.create_record({
        "slot_id": slot_id,
        "volunteer_id": volunteer_id,
        "supervision_adult_signup_id": supervision_id,
        "is_youth": is_youth,
        "waitlist_position": None,
        "checked_in_at": None,
        "checked_out_at": None,
        "credited_minutes": 0,
        "status": "REQUESTED",
    })
    db.signups[rec["id"]] = rec
    return ok(services.signup_view(rec), status=201)


@bp.get("/api/shift-signups")
def list_signups():
    ctx = require_auth()
    require_role(ctx, ALL_ROLES)
    limit, offset = pagination_args(request.args)
    items = services.list_view(
        db.signups.values(),
        {"slot_id": "slot_id", "volunteer_id": "volunteer_id", "status": "status",
         "supervision_adult_signup_id": "supervision_adult_signup_id"},
        request.args, services.signup_view,
    )
    total = len(items)
    return ok([services.signup_view(s) for s in items[offset:offset + limit]],
              pagination=(limit, offset, total))


@bp.get("/api/shift-signups/<signupId>")
def get_signup(signupId):
    ctx = require_auth()
    require_role(ctx, ALL_ROLES)
    return ok(services.signup_view(_get_signup(signupId)))


@bp.post("/api/shift-signups/<signupId>/confirm")
def confirm_signup(signupId):
    ctx = require_auth()
    require_role(ctx, STAFF)
    signup = _get_signup(signupId)
    if signup["status"] != "REQUESTED":
        raise err_state("SIGNUP")
    slot = _get_slot(signup["slot_id"])
    if slot["status"] not in {"OPEN", "FULL"}:
        raise err_state("SLOT")
    _check_slot_lock(slot)
    if signup["is_youth"]:
        _check_supervision(slot["id"], signup["supervision_adult_signup_id"])
    confirmed, youth, _ = services.slot_pools(slot["id"])
    fits_total = confirmed + 1 <= slot["capacity_total"]
    fits_youth = (not signup["is_youth"]) or (youth + 1 <= slot["capacity_youth"])
    if fits_total and fits_youth:
        # branch A: confirm in place
        signup["status"] = "CONFIRMED"
        services.bump(signup)
        services.recompute_slot_status(slot)
    else:
        # branch B: waitlist with the slot's monotonic position counter
        signup["status"] = "WAITLISTED"
        signup["waitlist_position"] = slot["next_waitlist_position"]
        services.bump(signup)
        slot["next_waitlist_position"] += 1
        services.bump(slot)
    return ok(services.signup_view(signup))


@bp.post("/api/shift-signups/<signupId>/cancel")
def cancel_signup(signupId):
    ctx = require_auth()
    require_role(ctx, FOUR)
    signup = _get_signup(signupId)
    if ctx.role in {"Volunteer", "GroupLeader"} and ctx.user_id != signup["volunteer_id"]:
        raise err_ownership()
    if signup["status"] not in {"REQUESTED", "WAITLISTED", "CONFIRMED"}:
        raise err_state("SIGNUP")
    if signup["status"] == "CONFIRMED":
        slot = _get_slot(signup["slot_id"])
        _check_slot_lock(slot)
    services.cancel_signup(signup)
    return ok(services.signup_view(signup))


@bp.post("/api/shift-signups/<signupId>/check-in")
def check_in_signup(signupId):
    ctx = require_auth()
    require_role(ctx, FOUR)
    signup = _get_signup(signupId)
    if ctx.role in {"Volunteer", "GroupLeader"} and ctx.user_id != signup["volunteer_id"]:
        raise err_ownership()
    if signup["status"] != "CONFIRMED":
        raise err_state("SIGNUP")
    slot = _get_slot(signup["slot_id"])
    now = clock.now()
    if not (slot["starts_at"] - timedelta(minutes=30) <= now <= slot["ends_at"]):
        raise err("ERR_OUTSIDE_CHECKIN_WINDOW",
                  "check-in window is [starts_at - 30min, ends_at]")
    signup["checked_in_at"] = now
    signup["credited_minutes"] = services.scheduled_minutes(slot)
    signup["status"] = "CHECKED_IN"
    services.bump(signup)
    return ok(services.signup_view(signup))


@bp.post("/api/shift-signups/<signupId>/check-out")
def check_out_signup(signupId):
    ctx = require_auth()
    require_role(ctx, FOUR)
    signup = _get_signup(signupId)
    if ctx.role in {"Volunteer", "GroupLeader"} and ctx.user_id != signup["volunteer_id"]:
        raise err_ownership()
    if signup["status"] != "CHECKED_IN":
        raise err_state("SIGNUP")
    slot = _get_slot(signup["slot_id"])
    now = clock.now()
    signup["checked_out_at"] = now
    actual = int((now - signup["checked_in_at"]).total_seconds() // 60)
    final = min(actual, services.scheduled_minutes(slot) + services.GRACE_MINUTES)
    signup["credited_minutes"] = max(0, final)
    signup["status"] = "COMPLETED"
    services.bump(signup)
    return ok(services.signup_view(signup))
