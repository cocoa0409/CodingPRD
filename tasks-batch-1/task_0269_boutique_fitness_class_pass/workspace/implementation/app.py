"""Boutique Fitness Class Pass API — Flask entry point.

In-memory only. No seeding. Fresh process == empty store (per-test isolation).
"""

import os

from flask import Flask

import db
import models
import services
import scheduling
from errors import ApiError, err
from middleware import get_principal, require_role
from response import success, error_response
from validation import (
    get_json_body, require, as_str, as_int, as_bool, as_enum,
    parse_dt, pagination_params, paginate,
)

app = Flask(__name__)
app.url_map.strict_slashes = False


# ============================================================================
# Error handling
# ============================================================================

@app.errorhandler(ApiError)
def handle_api_error(e):
    resp = error_response(e.error_id, e.message)
    resp.status_code = e.http_status
    return resp


@app.errorhandler(404)
def handle_404(e):
    resp = error_response("ERR_NOT_FOUND", "Resource not found")
    resp.status_code = 404
    return resp


@app.errorhandler(405)
def handle_405(e):
    resp = error_response("ERR_NOT_FOUND", "Method not allowed")
    resp.status_code = 404
    return resp


@app.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, ApiError):
        return handle_api_error(e)
    resp = error_response("ERR_INVALID_REQUEST", f"Unexpected error: {e}")
    resp.status_code = 422
    return resp


# ============================================================================
# Lookup helpers (existence — ERR_NOT_FOUND, §2.7)
# ============================================================================

def get_or_404(table, _id):
    rec = table.get(_id)
    if rec is None:
        raise err("ERR_NOT_FOUND", "Resource not found")
    return rec


def member_owns(role, user_id, member_id):
    """Ownership for entity_backed Member role (§2.1)."""
    if role == "Member" and user_id != member_id:
        raise err("ERR_FORBIDDEN", "Member may only act on their own resources")


# ============================================================================
# Studios
# ============================================================================

@app.route("/studios", methods=["POST"])
def create_studio():
    _, role = get_principal()
    require_role(role, {"NetworkAdmin"})
    body = get_json_body()
    name = as_str(require(body, "name"), "name")
    state_code = as_str(require(body, "state_code"), "state_code")
    tz = body.get("timezone", "UTC")
    if "timezone" in body and body["timezone"] is not None:
        tz = as_str(body["timezone"], "timezone")
    elif "timezone" in body and body["timezone"] is None:
        tz = "UTC"
    rec = models.base_record()
    rec.update({
        "name": name, "state_code": state_code, "timezone": tz,
        "status": "OPEN",
    })
    db.studios[rec["id"]] = rec
    return success(models.studio_out(rec), 201)


@app.route("/studios/<sid>", methods=["GET"])
def get_studio(sid):
    get_principal()
    rec = get_or_404(db.studios, sid)
    return success(models.studio_out(rec), 200)


@app.route("/studios/<sid>/close", methods=["POST"])
def close_studio(sid):
    _, role = get_principal()
    require_role(role, {"NetworkAdmin"})
    rec = get_or_404(db.studios, sid)
    rec["status"] = "CLOSED"
    models.touch(rec)
    return success(models.studio_out(rec), 200)


@app.route("/studios/<sid>/rooms", methods=["POST"])
def create_room(sid):
    _, role = get_principal()
    require_role(role, {"NetworkAdmin", "StudioManager"})
    studio = get_or_404(db.studios, sid)
    body = get_json_body()
    name = as_str(require(body, "name"), "name")
    cap = as_int(require(body, "physical_capacity"), "physical_capacity", minimum=1)
    rec = models.base_record()
    rec.update({
        "studio_id": studio["id"], "name": name,
        "physical_capacity": cap, "status": "ACTIVE",
    })
    db.rooms[rec["id"]] = rec
    return success(models.room_out(rec), 201)


@app.route("/studios/<sid>/rooms", methods=["GET"])
def list_rooms(sid):
    get_principal()
    get_or_404(db.studios, sid)
    limit, offset = pagination_params()
    items = [r for r in db.rooms.values() if r["studio_id"] == sid]
    page, meta = paginate(items, limit, offset)
    return success([models.room_out(r) for r in page], 200, pagination=meta)


@app.route("/rooms/<rid>/retire", methods=["POST"])
def retire_room(rid):
    _, role = get_principal()
    require_role(role, {"NetworkAdmin", "StudioManager"})
    rec = get_or_404(db.rooms, rid)
    rec["status"] = "RETIRED"
    models.touch(rec)
    return success(models.room_out(rec), 200)


# ============================================================================
# Instructors
# ============================================================================

@app.route("/instructors", methods=["POST"])
def create_instructor():
    _, role = get_principal()
    require_role(role, {"NetworkAdmin"})
    body = get_json_body()
    full_name = as_str(require(body, "full_name"), "full_name")
    home_studio_id = as_str(require(body, "home_studio_id"), "home_studio_id")
    get_or_404(db.studios, home_studio_id)
    rec = models.base_record()
    rec.update({
        "full_name": full_name, "home_studio_id": home_studio_id,
        "status": "ACTIVE",
    })
    db.instructors[rec["id"]] = rec
    return success(models.instructor_out(rec), 201)


@app.route("/instructors/<iid>", methods=["GET"])
def get_instructor(iid):
    get_principal()
    rec = get_or_404(db.instructors, iid)
    return success(models.instructor_out(rec), 200)


@app.route("/instructors", methods=["GET"])
def list_instructors():
    get_principal()
    limit, offset = pagination_params()
    items = list(db.instructors.values())
    hsi = None
    from flask import request
    if "home_studio_id" in request.args:
        hsi = request.args.get("home_studio_id")
        items = [i for i in items if i["home_studio_id"] == hsi]
    page, meta = paginate(items, limit, offset)
    return success([models.instructor_out(r) for r in page], 200, pagination=meta)


@app.route("/instructors/<iid>/deactivate", methods=["POST"])
def deactivate_instructor(iid):
    _, role = get_principal()
    require_role(role, {"NetworkAdmin"})
    rec = get_or_404(db.instructors, iid)
    rec["status"] = "INACTIVE"
    models.touch(rec)
    return success(models.instructor_out(rec), 200)


# ============================================================================
# Class templates
# ============================================================================

@app.route("/class-templates", methods=["POST"])
def create_template():
    _, role = get_principal()
    require_role(role, {"NetworkAdmin"})
    body = get_json_body()
    name = as_str(require(body, "name"), "name")
    duration = as_int(require(body, "duration_min"), "duration_min", minimum=15, maximum=240)
    cost = as_int(require(body, "credit_cost"), "credit_cost", minimum=1)
    window = 12
    if "late_cancel_window_hours" in body and body["late_cancel_window_hours"] is not None:
        window = as_int(body["late_cancel_window_hours"], "late_cancel_window_hours", minimum=0)
    rec = models.base_record()
    rec.update({
        "name": name, "duration_min": duration, "credit_cost": cost,
        "late_cancel_window_hours": window, "status": "ACTIVE",
    })
    db.class_templates[rec["id"]] = rec
    return success(models.template_out(rec), 201)


@app.route("/class-templates/<tid>", methods=["GET"])
def get_template(tid):
    get_principal()
    rec = get_or_404(db.class_templates, tid)
    return success(models.template_out(rec), 200)


# ============================================================================
# Package plans
# ============================================================================

@app.route("/package-plans", methods=["POST"])
def create_plan():
    _, role = get_principal()
    require_role(role, {"NetworkAdmin"})
    body = get_json_body()
    name = as_str(require(body, "name"), "name")
    kind = as_enum(require(body, "kind"), "kind", {"INTRO", "CREDIT_PACK", "MEMBERSHIP"})
    price = as_int(require(body, "price_cents"), "price_cents", minimum=0)
    grant = as_int(require(body, "grant_credits"), "grant_credits", minimum=1)
    validity = as_int(require(body, "validity_days"), "validity_days", minimum=1)
    rollover = 0
    if "rollover_cap" in body and body["rollover_cap"] is not None:
        rollover = as_int(body["rollover_cap"], "rollover_cap", minimum=0)
    freeze_max = 0
    if "freeze_max_days" in body and body["freeze_max_days"] is not None:
        freeze_max = as_int(body["freeze_max_days"], "freeze_max_days", minimum=0)
    intro_once = True
    if "intro_once_per_member" in body and body["intro_once_per_member"] is not None:
        intro_once = as_bool(body["intro_once_per_member"], "intro_once_per_member")
    rec = models.base_record()
    rec.update({
        "name": name, "kind": kind, "price_cents": price,
        "grant_credits": grant, "validity_days": validity,
        "rollover_cap": rollover, "freeze_max_days": freeze_max,
        "intro_once_per_member": intro_once, "status": "ACTIVE",
    })
    db.package_plans[rec["id"]] = rec
    return success(models.plan_out(rec), 201)


@app.route("/package-plans/<pid>", methods=["GET"])
def get_plan(pid):
    get_principal()
    rec = get_or_404(db.package_plans, pid)
    return success(models.plan_out(rec), 200)


# ============================================================================
# Members
# ============================================================================

@app.route("/members", methods=["POST"])
def create_member():
    _, role = get_principal()
    require_role(role, {"NetworkAdmin", "Member"})
    body = get_json_body()
    email = as_str(require(body, "email"), "email")
    full_name = as_str(require(body, "full_name"), "full_name")
    home_studio_id = as_str(require(body, "home_studio_id"), "home_studio_id")
    get_or_404(db.studios, home_studio_id)
    rec = models.base_record()
    rec.update({
        "email": email, "full_name": full_name,
        "home_studio_id": home_studio_id,
        "has_used_intro": False, "no_show_strikes": 0, "standing": "GOOD",
    })
    db.members[rec["id"]] = rec
    return success(models.member_out(rec), 201)


@app.route("/members/<mid>", methods=["GET"])
def get_member(mid):
    user_id, role = get_principal()
    rec = get_or_404(db.members, mid)
    member_owns(role, user_id, mid)
    return success(models.member_out(rec), 200)


@app.route("/members", methods=["GET"])
def list_members():
    _, role = get_principal()
    require_role(role, {"NetworkAdmin", "StudioManager"})
    limit, offset = pagination_params()
    from flask import request
    items = list(db.members.values())
    if "home_studio_id" in request.args:
        hsi = request.args.get("home_studio_id")
        items = [m for m in items if m["home_studio_id"] == hsi]
    page, meta = paginate(items, limit, offset)
    return success([models.member_out(r) for r in page], 200, pagination=meta)


@app.route("/members/<mid>/memberships", methods=["POST"])
def purchase_membership(mid):
    user_id, role = get_principal()
    require_role(role, {"NetworkAdmin", "Member"})
    member = get_or_404(db.members, mid)
    member_owns(role, user_id, mid)
    body = get_json_body()
    plan_id = as_str(require(body, "plan_id"), "plan_id")
    plan = get_or_404(db.package_plans, plan_id)
    # Intro-once check (§3.2, validation priority 11).
    if plan["kind"] == "INTRO" and plan["intro_once_per_member"] and member["has_used_intro"]:
        raise err("ERR_INTRO_ALREADY_USED", "Member has already used an intro plan")
    rec = models.base_record()
    rec.update({
        "member_id": member["id"], "plan_id": plan["id"],
        "status": "PENDING_PAYMENT", "credit_balance": 0,
        "activated_at": None, "cycle_start": None, "expires_at": None,
        "frozen_at": None, "freeze_days_used": 0,
        "rolled_over_credits": 0, "refund_cents": 0,
    })
    db.memberships[rec["id"]] = rec
    return success(models.membership_out(rec), 201)


@app.route("/members/<mid>/memberships", methods=["GET"])
def list_member_memberships(mid):
    user_id, role = get_principal()
    get_or_404(db.members, mid)
    member_owns(role, user_id, mid)
    limit, offset = pagination_params()
    items = [m for m in db.memberships.values() if m["member_id"] == mid]
    page, meta = paginate(items, limit, offset)
    return success([models.membership_out(r) for r in page], 200, pagination=meta)


# ============================================================================
# Memberships
# ============================================================================

@app.route("/memberships/<mid>", methods=["GET"])
def get_membership(mid):
    user_id, role = get_principal()
    rec = get_or_404(db.memberships, mid)
    member_owns(role, user_id, rec["member_id"])
    return success(models.membership_out(rec), 200)


@app.route("/memberships", methods=["GET"])
def list_memberships():
    _, role = get_principal()
    require_role(role, {"NetworkAdmin", "StudioManager"})
    limit, offset = pagination_params()
    from flask import request
    items = list(db.memberships.values())
    if "member_id" in request.args:
        items = [m for m in items if m["member_id"] == request.args.get("member_id")]
    if "plan_id" in request.args:
        items = [m for m in items if m["plan_id"] == request.args.get("plan_id")]
    page, meta = paginate(items, limit, offset)
    return success([models.membership_out(r) for r in page], 200, pagination=meta)


@app.route("/memberships/<mid>/wallet-entries", methods=["GET"])
def list_wallet_entries(mid):
    user_id, role = get_principal()
    rec = get_or_404(db.memberships, mid)
    member_owns(role, user_id, rec["member_id"])
    limit, offset = pagination_params()
    items = [w for w in db.wallet_entries.values() if w["membership_id"] == mid]
    page, meta = paginate(items, limit, offset)
    return success([models.wallet_entry_out(r) for r in page], 200, pagination=meta)


@app.route("/memberships/<mid>/freeze", methods=["POST"])
def freeze_membership(mid):
    user_id, role = get_principal()
    require_role(role, {"Member", "NetworkAdmin"})
    rec = get_or_404(db.memberships, mid)
    member_owns(role, user_id, rec["member_id"])
    body = get_json_body()
    expected = require(body, "expected_membership_version")
    expected = as_int(expected, "expected_membership_version")
    plan = db.package_plans[rec["plan_id"]]
    # State gate first (§2.9): freeze only defined from ACTIVE.
    if rec["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Membership is not ACTIVE")
    # OCC check after freezable state confirmed, before specific business rule (priority 7).
    if expected != rec["version"]:
        raise err("ERR_STALE_VERSION", "Membership version is stale")
    # Freeze business rule (priority 15).
    if (plan["kind"] != "MEMBERSHIP" or plan["freeze_max_days"] <= 0
            or rec["freeze_days_used"] >= plan["freeze_max_days"]):
        raise err("ERR_FREEZE_NOT_ALLOWED", "Freeze not permitted for this membership")
    rec["status"] = "FROZEN"
    rec["frozen_at"] = db.now_clock()
    models.touch(rec)
    return success(models.membership_out(rec), 200)


@app.route("/memberships/<mid>/unfreeze", methods=["POST"])
def unfreeze_membership(mid):
    import math
    from datetime import timedelta
    user_id, role = get_principal()
    require_role(role, {"Member", "NetworkAdmin"})
    rec = get_or_404(db.memberships, mid)
    member_owns(role, user_id, rec["member_id"])
    if rec["status"] != "FROZEN":
        raise err("ERR_INVALID_STATE", "Membership is not FROZEN")
    plan = db.package_plans[rec["plan_id"]]
    elapsed = (db.now_clock() - rec["frozen_at"]).total_seconds() / 86400.0
    span = math.ceil(elapsed) if elapsed > 0 else 0
    # Cap so freeze_days_used + span <= freeze_max_days.
    max_addable = plan["freeze_max_days"] - rec["freeze_days_used"]
    if span > max_addable:
        span = max_addable
    if span < 0:
        span = 0
    rec["freeze_days_used"] += span
    if rec["expires_at"] is not None:
        rec["expires_at"] = rec["expires_at"] + timedelta(days=span)
    rec["frozen_at"] = None
    rec["status"] = "ACTIVE"
    models.touch(rec)
    return success(models.membership_out(rec), 200)


@app.route("/memberships/<mid>/renew", methods=["POST"])
def renew_membership(mid):
    from datetime import timedelta
    _, role = get_principal()
    require_role(role, {"NetworkAdmin"})
    rec = get_or_404(db.memberships, mid)
    plan = db.package_plans[rec["plan_id"]]
    # State gate: renew defined only from ACTIVE.
    if rec["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Membership is not ACTIVE")
    if plan["kind"] != "MEMBERSHIP":
        raise err("ERR_INVALID_STATE", "Only MEMBERSHIP plans renew")
    if db.now_clock() < rec["expires_at"]:
        raise err("ERR_INVALID_STATE", "Cycle has not ended yet")
    balance = rec["credit_balance"]
    rolled = min(balance, plan["rollover_cap"])
    forfeited = balance - rolled
    if forfeited > 0:
        services.append_wallet_entry(
            rec["id"], "ROLLOVER_FORFEIT", -forfeited,
            f"Forfeited {forfeited} credits over rollover cap",
        )
    services.append_wallet_entry(
        rec["id"], "GRANT", plan["grant_credits"],
        f"Cycle renewal grant; {rolled} credits rolled over",
    )
    rec["rolled_over_credits"] = rolled
    rec["cycle_start"] = rec["expires_at"]
    rec["expires_at"] = rec["cycle_start"] + timedelta(days=plan["validity_days"])
    rec["freeze_days_used"] = 0
    models.recompute_credit_balance(rec["id"])
    models.touch(rec)
    return success(models.membership_out(rec), 200)


@app.route("/memberships/<mid>/cancel", methods=["POST"])
def cancel_membership(mid):
    user_id, role = get_principal()
    require_role(role, {"Member", "NetworkAdmin"})
    rec = get_or_404(db.memberships, mid)
    member_owns(role, user_id, rec["member_id"])
    if rec["status"] not in ("ACTIVE", "FROZEN"):
        raise err("ERR_INVALID_STATE", "Membership cannot be cancelled from its current state")
    refund = services.compute_cancellation_refund(rec)
    rec["refund_cents"] = refund
    services.forfeit_credits(rec, note="Credits forfeited on cancellation")
    rec["status"] = "CANCELLED"
    rec["frozen_at"] = None
    models.recompute_credit_balance(rec["id"])
    models.touch(rec)
    return success(models.membership_out(rec), 200)


# ============================================================================
# Fees
# ============================================================================

@app.route("/members/<mid>/fees", methods=["GET"])
def list_member_fees(mid):
    user_id, role = get_principal()
    get_or_404(db.members, mid)
    member_owns(role, user_id, mid)
    limit, offset = pagination_params()
    items = [f for f in db.fee_charges.values() if f["member_id"] == mid]
    page, meta = paginate(items, limit, offset)
    return success([models.fee_out(r) for r in page], 200, pagination=meta)


@app.route("/fees/<fid>", methods=["GET"])
def get_fee(fid):
    user_id, role = get_principal()
    rec = get_or_404(db.fee_charges, fid)
    member_owns(role, user_id, rec["member_id"])
    return success(models.fee_out(rec), 200)


@app.route("/fees", methods=["GET"])
def list_fees():
    user_id, role = get_principal()
    limit, offset = pagination_params()
    from flask import request
    items = list(db.fee_charges.values())
    if "reservation_id" in request.args:
        items = [f for f in items if f["reservation_id"] == request.args.get("reservation_id")]
    if "member_id" in request.args:
        items = [f for f in items if f["member_id"] == request.args.get("member_id")]
    if role == "Member":
        items = [f for f in items if f["member_id"] == user_id]
    page, meta = paginate(items, limit, offset)
    return success([models.fee_out(r) for r in page], 200, pagination=meta)


@app.route("/fees/<fid>/waive", methods=["POST"])
def waive_fee(fid):
    _, role = get_principal()
    require_role(role, {"StudioManager", "NetworkAdmin"})
    rec = get_or_404(db.fee_charges, fid)
    if rec["status"] != "ASSESSED":
        raise err("ERR_INVALID_STATE", "Fee is not ASSESSED")
    rec["status"] = "WAIVED"
    models.touch(rec)
    # Strikes are the count of ASSESSED fees; flipping to WAIVED removes its
    # contribution. Recompute strikes/standing for the member.
    services.recompute_standing(rec["member_id"])
    return success(models.fee_out(rec), 200)


# ============================================================================
# Sessions
# ============================================================================

def _validate_session_create_fields(body):
    studio_id = as_str(require(body, "studio_id"), "studio_id")
    room_id = as_str(require(body, "room_id"), "room_id")
    instructor_id = as_str(require(body, "instructor_id"), "instructor_id")
    template_id = as_str(require(body, "template_id"), "template_id")
    require(body, "starts_at")
    seat_capacity = as_int(require(body, "seat_capacity"), "seat_capacity", minimum=1)
    waitlist_capacity = 5
    if "waitlist_capacity" in body and body["waitlist_capacity"] is not None:
        waitlist_capacity = as_int(body["waitlist_capacity"], "waitlist_capacity", minimum=0)
    starts_at = parse_dt(body["starts_at"], "starts_at")
    return studio_id, room_id, instructor_id, template_id, starts_at, seat_capacity, waitlist_capacity


@app.route("/sessions", methods=["POST"])
def create_session():
    from datetime import timedelta
    _, role = get_principal()
    require_role(role, {"StudioManager", "NetworkAdmin"})
    body = get_json_body()
    (studio_id, room_id, instructor_id, template_id, starts_at,
     seat_capacity, waitlist_capacity) = _validate_session_create_fields(body)
    # Existence (priority 3) — validate referenced ids.
    studio = get_or_404(db.studios, studio_id)
    room = get_or_404(db.rooms, room_id)
    instructor = get_or_404(db.instructors, instructor_id)
    template = get_or_404(db.class_templates, template_id)
    # Room must belong to the studio.
    if room["studio_id"] != studio_id:
        raise err("ERR_NOT_FOUND", "Room does not belong to studio")
    # Dependency state (priority 8) before conflicts/capacity.
    scheduling.validate_session_dependencies(studio, room, instructor)
    ends_at = starts_at + timedelta(minutes=template["duration_min"])
    # Instructor conflict (12) then room conflict (13) then capacity (14).
    scheduling.check_instructor_conflict(instructor_id, starts_at, ends_at, studio_id)
    scheduling.check_room_conflict(room_id, starts_at, ends_at)
    if seat_capacity > room["physical_capacity"]:
        raise err("ERR_CAPACITY_EXCEEDS_ROOM", "seat_capacity exceeds room physical_capacity")
    rec = models.base_record()
    rec.update({
        "studio_id": studio_id, "room_id": room_id,
        "instructor_id": instructor_id, "template_id": template_id,
        "starts_at": starts_at, "ends_at": ends_at,
        "seat_capacity": seat_capacity, "waitlist_capacity": waitlist_capacity,
        "status": "SCHEDULED", "booked_count": 0, "waitlisted_count": 0,
    })
    db.class_sessions[rec["id"]] = rec
    return success(models.session_out(rec), 201)


@app.route("/sessions/<sid>", methods=["GET"])
def get_session(sid):
    get_principal()
    rec = get_or_404(db.class_sessions, sid)
    return success(models.session_out(rec), 200)


@app.route("/sessions", methods=["GET"])
def list_sessions():
    get_principal()
    limit, offset = pagination_params()
    from flask import request
    items = list(db.class_sessions.values())
    for key in ("studio_id", "room_id", "instructor_id", "template_id"):
        if key in request.args:
            val = request.args.get(key)
            items = [s for s in items if s[key] == val]
    page, meta = paginate(items, limit, offset)
    return success([models.session_out(r) for r in page], 200, pagination=meta)


@app.route("/sessions/<sid>", methods=["PATCH"])
def update_session(sid):
    from datetime import timedelta
    _, role = get_principal()
    require_role(role, {"StudioManager", "NetworkAdmin"})
    rec = get_or_404(db.class_sessions, sid)
    if rec["status"] in ("CANCELLED", "COMPLETED"):
        raise err("ERR_INVALID_STATE", "Session cannot be edited after completion/cancel")
    body = get_json_body()

    new_seat_capacity = rec["seat_capacity"]
    new_starts_at = rec["starts_at"]
    new_room_id = rec["room_id"]
    new_waitlist_capacity = rec["waitlist_capacity"]

    if "seat_capacity" in body and body["seat_capacity"] is not None:
        new_seat_capacity = as_int(body["seat_capacity"], "seat_capacity", minimum=1)
    if "waitlist_capacity" in body and body["waitlist_capacity"] is not None:
        new_waitlist_capacity = as_int(body["waitlist_capacity"], "waitlist_capacity", minimum=0)
    if "starts_at" in body and body["starts_at"] is not None:
        new_starts_at = parse_dt(body["starts_at"], "starts_at")
    if "room_id" in body and body["room_id"] is not None:
        new_room_id = as_str(body["room_id"], "room_id")

    studio = get_or_404(db.studios, rec["studio_id"])
    room = get_or_404(db.rooms, new_room_id)
    instructor = get_or_404(db.instructors, rec["instructor_id"])
    template = db.class_templates[rec["template_id"]]
    if room["studio_id"] != rec["studio_id"]:
        raise err("ERR_NOT_FOUND", "Room does not belong to studio")

    # Re-run dependency, conflict, and capacity checks (§3.5).
    scheduling.validate_session_dependencies(studio, room, instructor)
    new_ends_at = new_starts_at + timedelta(minutes=template["duration_min"])
    scheduling.check_instructor_conflict(
        rec["instructor_id"], new_starts_at, new_ends_at, rec["studio_id"],
        exclude_session_id=sid,
    )
    scheduling.check_room_conflict(new_room_id, new_starts_at, new_ends_at, exclude_session_id=sid)
    if new_seat_capacity > room["physical_capacity"]:
        raise err("ERR_CAPACITY_EXCEEDS_ROOM", "seat_capacity exceeds room physical_capacity")

    capacity_increased = new_seat_capacity > rec["seat_capacity"]
    rec["seat_capacity"] = new_seat_capacity
    rec["waitlist_capacity"] = new_waitlist_capacity
    rec["starts_at"] = new_starts_at
    rec["ends_at"] = new_ends_at
    rec["room_id"] = new_room_id
    models.touch(rec)

    # Bulk waitlist promotion on capacity increase for a FULL session (§3.7).
    if capacity_increased and rec["status"] in ("OPEN", "FULL"):
        services.run_promotion(sid)

    return success(models.session_out(rec), 200)


@app.route("/sessions/<sid>/publish", methods=["POST"])
def publish_session(sid):
    _, role = get_principal()
    require_role(role, {"StudioManager", "NetworkAdmin"})
    rec = get_or_404(db.class_sessions, sid)
    if rec["status"] != "SCHEDULED":
        raise err("ERR_INVALID_STATE", "Only a SCHEDULED session can be published")
    studio = get_or_404(db.studios, rec["studio_id"])
    room = get_or_404(db.rooms, rec["room_id"])
    instructor = get_or_404(db.instructors, rec["instructor_id"])
    scheduling.validate_session_dependencies(studio, room, instructor)
    scheduling.check_instructor_conflict(
        rec["instructor_id"], rec["starts_at"], rec["ends_at"], rec["studio_id"],
        exclude_session_id=sid,
    )
    scheduling.check_room_conflict(rec["room_id"], rec["starts_at"], rec["ends_at"], exclude_session_id=sid)
    rec["status"] = "OPEN"
    models.touch(rec)
    return success(models.session_out(rec), 200)


@app.route("/sessions/<sid>/cancel", methods=["POST"])
def cancel_session(sid):
    _, role = get_principal()
    require_role(role, {"StudioManager", "NetworkAdmin"})
    rec = get_or_404(db.class_sessions, sid)
    if rec["status"] not in ("SCHEDULED", "OPEN", "FULL"):
        raise err("ERR_INVALID_STATE", "Session cannot be cancelled from its current state")
    # Cascade: release every BOOKED/WAITLISTED reservation; refund BOOKED credits.
    for r in db.reservations.values():
        if r["session_id"] != sid:
            continue
        if r["booking_status"] in ("BOOKED", "WAITLISTED"):
            was_booked = r["booking_status"] == "BOOKED"
            r["booking_status"] = "RELEASED"
            r["attendance_status"] = "CANCELLED"
            r["waitlist_position"] = 0
            if was_booked and r["credits_charged"] > 0:
                services.append_wallet_entry(
                    r["membership_id"], "CANCEL_REFUND", r["credits_charged"],
                    "Seat credit refunded (studio cancelled session)",
                    reservation_id=r["id"],
                )
            models.touch(r)
    rec["status"] = "CANCELLED"
    services.recompute_session_counts(sid)
    models.touch(rec)
    return success(models.session_out(rec), 200)


# ============================================================================
# Reservations
# ============================================================================

@app.route("/sessions/<sid>/reservations", methods=["POST"])
def create_reservation(sid):
    user_id, role = get_principal()
    require_role(role, {"Member", "NetworkAdmin"})
    sess = get_or_404(db.class_sessions, sid)
    body = get_json_body()
    membership_id = as_str(require(body, "membership_id"), "membership_id")
    expected = require(body, "expected_session_version")
    expected = as_int(expected, "expected_session_version")
    membership = get_or_404(db.memberships, membership_id)
    member_id = membership["member_id"]
    member = db.members[member_id]
    # Ownership: a Member books only on their own membership.
    member_owns(role, user_id, member_id)
    template = db.class_templates[sess["template_id"]]

    # Priority 6: session bookable (OPEN/FULL).
    if sess["status"] not in ("OPEN", "FULL"):
        raise err("ERR_SESSION_NOT_BOOKABLE", "Session is not bookable")
    # Priority 7: OCC after bookable confirmed.
    if expected != sess["version"]:
        raise err("ERR_STALE_VERSION", "Session version is stale")
    # Priority 9: member standing.
    if member["standing"] != "GOOD":
        raise err("ERR_MEMBER_RESTRICTED", "Member is restricted")
    # Priority 16: membership active (before duplicate/waitlist/credit).
    if membership["status"] != "ACTIVE":
        raise err("ERR_MEMBERSHIP_INACTIVE", "Membership is not active")
    # Priority 17: duplicate non-RELEASED reservation on the same session.
    for r in db.reservations.values():
        if (r["session_id"] == sid and r["member_id"] == member_id
                and r["booking_status"] != "RELEASED"):
            raise err("ERR_DUPLICATE_RESERVATION", "Member already has a reservation on this session")

    cost = template["credit_cost"]
    free_seat = sess["status"] == "OPEN" and sess["booked_count"] < sess["seat_capacity"]

    rec = models.base_record()
    rec.update({
        "session_id": sid, "member_id": member_id, "membership_id": membership_id,
        "booking_status": "WAITLISTED", "attendance_status": "PENDING",
        "credits_charged": 0, "waitlist_position": 0,
        "late_fee_cents": 0, "promoted_at": None,
    })

    if free_seat:
        # Priority 19: sufficient credits for immediate booking.
        if membership["credit_balance"] < cost:
            raise err("ERR_INSUFFICIENT_CREDITS", "Insufficient credits to reserve a seat")
        db.reservations[rec["id"]] = rec
        services.append_wallet_entry(
            membership_id, "RESERVE_DEBIT", -cost,
            "Seat reserved", reservation_id=rec["id"],
        )
        rec["booking_status"] = "BOOKED"
        rec["credits_charged"] = cost
        sess["booked_count"] += 1
        if sess["booked_count"] == sess["seat_capacity"]:
            sess["status"] = "FULL"
    else:
        # Priority 18: waitlist must have room.
        if sess["waitlisted_count"] >= sess["waitlist_capacity"]:
            raise err("ERR_WAITLIST_FULL", "Waitlist is full")
        db.reservations[rec["id"]] = rec
        rec["booking_status"] = "WAITLISTED"
        sess["waitlisted_count"] += 1
        services.recompute_waitlist_positions(sid)

    models.touch(sess)  # session.version bumps by 1 on a reservation write (OCC).
    return success(models.reservation_out(rec), 201)


@app.route("/sessions/<sid>/reservations", methods=["GET"])
def list_session_reservations(sid):
    get_principal()
    get_or_404(db.class_sessions, sid)
    limit, offset = pagination_params()
    items = [r for r in db.reservations.values() if r["session_id"] == sid]
    page, meta = paginate(items, limit, offset)
    return success([models.reservation_out(r) for r in page], 200, pagination=meta)


@app.route("/reservations/<rid>", methods=["GET"])
def get_reservation(rid):
    user_id, role = get_principal()
    rec = get_or_404(db.reservations, rid)
    member_owns(role, user_id, rec["member_id"])
    return success(models.reservation_out(rec), 200)


@app.route("/reservations/<rid>/wallet-entries", methods=["GET"])
def list_reservation_wallet_entries(rid):
    user_id, role = get_principal()
    rec = get_or_404(db.reservations, rid)
    member_owns(role, user_id, rec["member_id"])
    limit, offset = pagination_params()
    items = [w for w in db.wallet_entries.values() if w["reservation_id"] == rid]
    page, meta = paginate(items, limit, offset)
    return success([models.wallet_entry_out(r) for r in page], 200, pagination=meta)


@app.route("/reservations", methods=["GET"])
def list_reservations():
    user_id, role = get_principal()
    limit, offset = pagination_params()
    from flask import request
    items = list(db.reservations.values())
    if "member_id" in request.args:
        items = [r for r in items if r["member_id"] == request.args.get("member_id")]
    if "membership_id" in request.args:
        items = [r for r in items if r["membership_id"] == request.args.get("membership_id")]
    if role == "Member":
        items = [r for r in items if r["member_id"] == user_id]
    page, meta = paginate(items, limit, offset)
    return success([models.reservation_out(r) for r in page], 200, pagination=meta)


@app.route("/reservations/<rid>/cancel", methods=["POST"])
def cancel_reservation(rid):
    from datetime import timedelta
    user_id, role = get_principal()
    require_role(role, {"Member", "NetworkAdmin"})
    rec = get_or_404(db.reservations, rid)
    member_owns(role, user_id, rec["member_id"])
    sess = db.class_sessions[rec["session_id"]]
    template = db.class_templates[sess["template_id"]]

    if rec["booking_status"] == "RELEASED":
        raise err("ERR_INVALID_STATE", "Reservation already released")

    if rec["booking_status"] == "WAITLISTED":
        rec["booking_status"] = "RELEASED"
        rec["attendance_status"] = "CANCELLED"
        rec["waitlist_position"] = 0
        models.touch(rec)
        services.recompute_session_counts(rec["session_id"])
        services.recompute_waitlist_positions(rec["session_id"])
        return success(models.reservation_out(rec), 200)

    # BOOKED: distinguish early vs late by the late-cancel window.
    window_start = sess["starts_at"] - timedelta(hours=template["late_cancel_window_hours"])
    now = db.now_clock()
    is_late = now >= window_start  # at/after window start (and before starts_at)

    refund = rec["credits_charged"]
    rec["booking_status"] = "RELEASED"
    if refund > 0:
        services.append_wallet_entry(
            rec["membership_id"], "CANCEL_REFUND", refund,
            "Seat credit refunded on cancellation", reservation_id=rec["id"],
        )

    if is_late:
        rec["attendance_status"] = "LATE_CANCELLED"
        fee = services.assess_fee(rec["member_id"], rec["id"], "LATE_CANCEL", credit_refunded=True)
        rec["late_fee_cents"] = fee["amount_cents"]
    else:
        rec["attendance_status"] = "CANCELLED"

    models.touch(rec)
    if sess["status"] in ("OPEN", "FULL"):
        sess["booked_count"] = max(0, sess["booked_count"] - 1)
        services.run_promotion(rec["session_id"])
    else:
        services.recompute_session_counts(rec["session_id"])
    return success(models.reservation_out(rec), 200)


@app.route("/reservations/<rid>/check_in", methods=["POST"])
def check_in_reservation(rid):
    from datetime import timedelta
    _, role = get_principal()
    require_role(role, {"StudioManager", "NetworkAdmin"})
    rec = get_or_404(db.reservations, rid)
    sess = db.class_sessions[rec["session_id"]]
    # State gate: booking_status BOOKED and attendance PENDING, session OPEN/FULL.
    if not (rec["booking_status"] == "BOOKED" and rec["attendance_status"] == "PENDING"
            and sess["status"] in ("OPEN", "FULL")):
        raise err("ERR_INVALID_STATE", "Reservation not in a checkable state")
    lead = sess["starts_at"] - timedelta(hours=services.CHECKIN_LEAD_HOURS)
    if db.now_clock() < lead:
        raise err("ERR_INVALID_CANCEL_WINDOW", "Check-in is before the allowed lead window")
    rec["attendance_status"] = "CHECKED_IN"
    models.touch(rec)
    return success(models.reservation_out(rec), 200)


# ============================================================================
# Test-driving / ops endpoints
# ============================================================================

@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    _, role = get_principal()
    require_role(role, {"NetworkAdmin"})
    body = get_json_body()
    raw = require(body, "to_iso8601")
    dt = parse_dt(raw, "to_iso8601")
    db.set_clock(dt)
    return success({}, 200)


@app.route("/_payments/capture", methods=["POST"])
def capture_payment():
    from datetime import timedelta
    _, role = get_principal()
    require_role(role, {"NetworkAdmin"})
    body = get_json_body()
    membership_id = as_str(require(body, "membership_id"), "membership_id")
    outcome = as_str(require(body, "outcome"), "outcome")
    membership = get_or_404(db.memberships, membership_id)
    if membership["status"] != "PENDING_PAYMENT":
        raise err("ERR_INVALID_STATE", "Membership is not PENDING_PAYMENT")
    if outcome != "CAPTURED":
        # Non-captured outcome leaves the membership pending; report invalid state-ish.
        raise err("ERR_INVALID_REQUEST", "Payment outcome was not CAPTURED")
    plan = db.package_plans[membership["plan_id"]]
    now = db.now_clock()
    membership["status"] = "ACTIVE"
    membership["activated_at"] = now
    membership["cycle_start"] = now
    membership["expires_at"] = now + timedelta(days=plan["validity_days"])
    services.append_wallet_entry(
        membership_id, "GRANT", plan["grant_credits"],
        "Initial credit grant on activation",
    )
    if plan["kind"] == "INTRO":
        member = db.members[membership["member_id"]]
        member["has_used_intro"] = True
        models.touch(member)
    models.recompute_credit_balance(membership_id)
    models.touch(membership)
    return success(models.membership_out(membership), 200)


@app.route("/_ops/run_completion", methods=["POST"])
def run_completion():
    _, role = get_principal()
    require_role(role, {"NetworkAdmin"})
    now = db.now_clock()
    for sess in list(db.class_sessions.values()):
        if sess["status"] not in ("OPEN", "FULL"):
            continue
        if now < sess["ends_at"]:
            continue
        for r in db.reservations.values():
            if r["session_id"] != sess["id"]:
                continue
            if r["booking_status"] == "BOOKED" and r["attendance_status"] == "PENDING":
                r["attendance_status"] = "NO_SHOW"
                fee = services.assess_fee(r["member_id"], r["id"], "NO_SHOW", credit_refunded=False)
                r["late_fee_cents"] = fee["amount_cents"]
                models.touch(r)
            elif r["booking_status"] == "WAITLISTED":
                r["booking_status"] = "RELEASED"
                r["attendance_status"] = "CANCELLED"
                r["waitlist_position"] = 0
                models.touch(r)
        sess["status"] = "COMPLETED"
        services.recompute_session_counts(sess["id"])
        models.touch(sess)
    return success({}, 200)


@app.route("/_ops/run_expiry", methods=["POST"])
def run_expiry():
    _, role = get_principal()
    require_role(role, {"NetworkAdmin"})
    now = db.now_clock()
    for membership in list(db.memberships.values()):
        if membership["status"] not in ("ACTIVE", "FROZEN"):
            continue
        if membership["expires_at"] is None or now < membership["expires_at"]:
            continue
        plan = db.package_plans[membership["plan_id"]]
        # ACTIVE MEMBERSHIP plans do not auto-expire (they renew); FROZEN always expires.
        if membership["status"] == "ACTIVE" and plan["kind"] == "MEMBERSHIP":
            continue
        services.forfeit_credits(membership, note="Credits forfeited on expiry")
        membership["status"] = "EXPIRED"
        membership["frozen_at"] = None
        models.recompute_credit_balance(membership["id"])
        models.touch(membership)
    return success({}, 200)


# ============================================================================
# Entry point
# ============================================================================

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
