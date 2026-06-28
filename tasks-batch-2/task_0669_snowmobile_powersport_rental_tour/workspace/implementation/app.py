"""Snowmobile / Powersport Rental & Guided Tour API — Flask entry point.

Implements the PRD verbatim. In-memory storage only; no seeding at startup.
"""
import os

from flask import Flask, request

import calculations as calc
import serialize as ser
from auth import authenticate, authorize
from clock import clock
from common import (
    age_at,
    parse_datetime,
    parse_pagination,
    paginate,
    require_str,
    require_int,
    require_number,
    require_enum,
    require_datetime,
    require_field,
    optional_enum,
    class_rank,
)
from db import (
    db,
    stamp_common_create,
    stamp_lightweight_create,
    touch,
    clock_iso,
)
from errors import (
    ApiError,
    err,
    ERR_UNAUTHORIZED,
    ERR_OWNERSHIP_REQUIRED,
    ERR_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_DEPARTURE_NOT_OPEN,
    ERR_WAIVER_NOT_SIGNED,
    ERR_RIDER_UNDERAGE,
    ERR_TRAINING_REQUIRED,
    ERR_UNIT_CLASS_TOO_LOW,
    ERR_UNIT_DOUBLE_BOOKED,
    ERR_GEAR_DOUBLE_BOOKED,
    ERR_GUIDE_DOUBLE_BOOKED,
    ERR_GUIDE_CLASS_TOO_LOW,
    ERR_GUIDE_RATIO_UNMET,
    ERR_TRAIL_CLOSED,
    ERR_DEPARTURE_FULL,
    ERR_STALE_VERSION,
    ERR_DUPLICATE,
    ERR_GEAR_KIND_MISMATCH,
    ERR_FUEL_FRACTION_REQUIRED,
)
from response import success, error as error_response
import services as svc

app = Flask(__name__)

CLASSES = {"TRAIL", "UTILITY", "MOUNTAIN"}


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------
@app.errorhandler(ApiError)
def handle_api_error(e):
    return error_response(e.error_id, e.message, e.http_status)


@app.errorhandler(404)
def handle_404(e):
    return error_response("ERR_NOT_FOUND", "Resource not found", 404)


@app.errorhandler(405)
def handle_405(e):
    return error_response("ERR_NOT_FOUND", "Method not allowed", 404)


@app.errorhandler(500)
def handle_500(e):
    return error_response("ERR_INVALID_REQUEST", "Internal error", 422)


def body():
    """Parse the JSON body; an absent/empty body is treated as {}."""
    if not request.data:
        return {}
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        err(ERR_INVALID_REQUEST, "Request body must be a JSON object")
    return data


# ---------------------------------------------------------------------------
# Lookup helpers (existence — ERR_NOT_FOUND, priority 4)
# ---------------------------------------------------------------------------
def get_member(mid):
    m = db.members.get(mid)
    if m is None:
        err(ERR_NOT_FOUND, "Member not found")
    return m


def get_guide(gid):
    g = db.guides.get(gid)
    if g is None:
        err(ERR_NOT_FOUND, "Guide not found")
    return g


def get_trail(tid):
    t = db.trails.get(tid)
    if t is None:
        err(ERR_NOT_FOUND, "Trail not found")
    return t


def get_unit(uid):
    u = db.units.get(uid)
    if u is None:
        err(ERR_NOT_FOUND, "Unit not found")
    return u


def get_gear(gid):
    g = db.gear_items.get(gid)
    if g is None:
        err(ERR_NOT_FOUND, "Gear item not found")
    return g


def get_departure(did):
    d = db.tour_departures.get(did)
    if d is None:
        err(ERR_NOT_FOUND, "Tour departure not found")
    return d


def get_reservation(rid):
    r = db.reservations.get(rid)
    if r is None:
        err(ERR_NOT_FOUND, "Reservation not found")
    return r


def get_settlement(sid):
    s = db.settlements.get(sid)
    if s is None:
        err(ERR_NOT_FOUND, "Settlement not found")
    return s


# ===========================================================================
# Members
# ===========================================================================
@app.route("/members/register", methods=["POST"])
def register_member():
    # Anonymous endpoint: no auth required (lone exception to auth gate).
    data = body()
    full_name = require_str(data, "full_name")
    email = require_str(data, "email")
    dob = require_str(data, "date_of_birth")
    # Validate date_of_birth format.
    from common import parse_date
    try:
        parse_date(dob)
    except Exception:
        err(ERR_INVALID_REQUEST, "date_of_birth must be an ISO 8601 date (YYYY-MM-DD)")

    tier = optional_enum(data, "membership_tier", {"NONE", "SEASON", "PREMIER"}, default="NONE")
    expires = None
    if "membership_expires_at" in data and data["membership_expires_at"] is not None:
        try:
            parse_datetime(data["membership_expires_at"])
        except Exception:
            err(ERR_INVALID_REQUEST, "membership_expires_at must be an ISO 8601 datetime")
        expires = data["membership_expires_at"]
    if tier == "NONE":
        expires = None

    # Email uniqueness (case-insensitive) — ERR_DUPLICATE.
    lowered = email.lower()
    for m in db.members.values():
        if m["email"].lower() == lowered:
            err(ERR_DUPLICATE, "Email already registered")

    member = stamp_common_create({
        "full_name": full_name,
        "email": email,
        "date_of_birth": dob,
        "membership_tier": tier,
        "membership_expires_at": expires,
        "waiver_status": "UNSIGNED",
        "waiver_signed_at": None,
        "training_level": "NONE",
        "deposit_hold_cents": 0,
        "lifetime_damage_strikes": 0,
    })
    db.members[member["id"]] = member
    return success(ser.member_out(member), 201)


@app.route("/members/<mid>", methods=["GET"])
def fetch_member(mid):
    p = authenticate()
    authorize(p, {"Member", "DispatchOperator", "PlatformAdmin"})
    member = get_member(mid)
    # Member ownership: a Member may only read their own member record.
    if p.role == "Member" and p.user_id != mid:
        err(ERR_OWNERSHIP_REQUIRED, "Members may only access their own record")
    return success(ser.member_out(member), 200)


@app.route("/members/<mid>/sign-waiver", methods=["POST"])
def sign_waiver(mid):
    p = authenticate()
    authorize(p, {"Member"})
    member = get_member(mid)
    if p.user_id != mid:
        err(ERR_OWNERSHIP_REQUIRED, "Members may only sign their own waiver")
    data = body()
    guardian_ack = data.get("guardian_ack", False)
    if guardian_ack is not None and not isinstance(guardian_ack, bool):
        err(ERR_INVALID_REQUEST, "guardian_ack must be a boolean")

    # State gate: defined only from UNSIGNED or EXPIRED.
    if member["waiver_status"] not in ("UNSIGNED", "EXPIRED"):
        err(ERR_INVALID_STATE, "Waiver cannot be signed from its current state")

    # Age gate: >= 18 at signing instant OR guardian_ack true.
    sign_age = age_at(member["date_of_birth"], clock.now())
    if sign_age < calc.WAIVER_ADULT_AGE and not guardian_ack:
        err(ERR_INVALID_STATE, "Minor must supply guardian_ack to sign the waiver")

    member["waiver_status"] = "SIGNED"
    member["waiver_signed_at"] = clock_iso()
    touch(member)
    return success(ser.member_out(member), 200)


@app.route("/members/<mid>/expire-waiver", methods=["POST"])
def expire_waiver(mid):
    p = authenticate()
    authorize(p, {"DispatchOperator", "PlatformAdmin"})
    member = get_member(mid)
    svc.reevaluate_member_waiver(member)
    return success(ser.member_out(member), 200)


@app.route("/members/<mid>/complete-training", methods=["POST"])
def complete_training(mid):
    p = authenticate()
    authorize(p, {"DispatchOperator"})
    member = get_member(mid)
    data = body()
    level = require_enum(data, "level", {"BASIC", "ADVANCED"})

    current = member["training_level"]
    # NONE -> BASIC requires level==BASIC and waiver SIGNED.
    # BASIC -> ADVANCED requires level==ADVANCED.
    if current == "NONE":
        if level != "BASIC":
            err(ERR_INVALID_STATE, "Training must advance to BASIC from NONE")
        if member["waiver_status"] != "SIGNED":
            err(ERR_INVALID_STATE, "Waiver must be SIGNED before BASIC training")
        member["training_level"] = "BASIC"
        touch(member)
    elif current == "BASIC":
        if level != "ADVANCED":
            err(ERR_INVALID_STATE, "Training must advance to ADVANCED from BASIC")
        member["training_level"] = "ADVANCED"
        touch(member)
    else:
        # ADVANCED is terminal.
        err(ERR_INVALID_STATE, "Training is already at its maximum level")
    return success(ser.member_out(member), 200)


@app.route("/members/<mid>/reservations", methods=["GET"])
def list_member_reservations(mid):
    p = authenticate()
    authorize(p, {"Member", "DispatchOperator", "PlatformAdmin"})
    get_member(mid)
    if p.role == "Member" and p.user_id != mid:
        err(ERR_OWNERSHIP_REQUIRED, "Members may only list their own reservations")
    limit, offset = parse_pagination(request.args)
    status_filter = request.args.get("reservation_status")
    items = [r for r in db.reservations.values() if r["member_id"] == mid]
    if status_filter is not None:
        items = [r for r in items if r["reservation_status"] == status_filter]
    page, pmeta = paginate(items, limit, offset)
    return success([ser.reservation_out(r) for r in page], 200, pagination=pmeta)


# ===========================================================================
# Guides
# ===========================================================================
@app.route("/guides", methods=["POST"])
def create_guide():
    p = authenticate()
    authorize(p, {"DispatchOperator", "PlatformAdmin"})
    data = body()
    full_name = require_str(data, "full_name")
    max_class = require_enum(data, "max_class", CLASSES)
    guide = stamp_common_create({
        "full_name": full_name,
        "max_class": max_class,
        "status": "AVAILABLE",
    })
    db.guides[guide["id"]] = guide
    return success(ser.guide_out(guide), 201)


@app.route("/guides/<gid>", methods=["GET"])
def fetch_guide(gid):
    p = authenticate()
    authorize(p, {"Guide", "DispatchOperator", "PlatformAdmin"})
    guide = get_guide(gid)
    if p.role == "Guide" and p.user_id != gid:
        err(ERR_OWNERSHIP_REQUIRED, "Guides may only access their own record")
    return success(ser.guide_out(guide), 200)


@app.route("/guides/<gid>/assignments", methods=["GET"])
def list_guide_assignments(gid):
    p = authenticate()
    authorize(p, {"Guide", "DispatchOperator", "PlatformAdmin"})
    get_guide(gid)
    if p.role == "Guide" and p.user_id != gid:
        err(ERR_OWNERSHIP_REQUIRED, "Guides may only list their own assignments")
    limit, offset = parse_pagination(request.args)
    items = [a for a in db.guide_assignments.values() if a["guide_id"] == gid]
    active_filter = _parse_bool_query("active")
    if active_filter is not None:
        items = [a for a in items if a["active"] == active_filter]
    page, pmeta = paginate(items, limit, offset)
    return success([ser.guide_assignment_out(a) for a in page], 200, pagination=pmeta)


# ===========================================================================
# Trails
# ===========================================================================
@app.route("/trails", methods=["POST"])
def create_trail():
    p = authenticate()
    authorize(p, {"DispatchOperator", "PlatformAdmin"})
    data = body()
    name = require_str(data, "name")
    required_class = require_enum(data, "required_class", CLASSES)
    max_riders = require_int(data, "max_riders", minimum=1)
    trail = stamp_common_create({
        "name": name,
        "required_class": required_class,
        "max_riders": max_riders,
        "condition": "OPEN",
    })
    db.trails[trail["id"]] = trail
    return success(ser.trail_out(trail), 201)


@app.route("/trails/<tid>", methods=["GET"])
def fetch_trail(tid):
    p = authenticate()
    authorize(p, {"Member", "Guide", "DispatchOperator", "PlatformAdmin"})
    trail = get_trail(tid)
    return success(ser.trail_out(trail), 200)


@app.route("/trails/<tid>/closure", methods=["POST"])
def post_closure(tid):
    p = authenticate()
    authorize(p, {"DispatchOperator"})
    trail = get_trail(tid)
    data = body()
    new_condition = require_enum(data, "new_condition", {"OPEN", "CAUTION", "CLOSED"})
    reason = require_str(data, "reason")

    cancelled_count = 0
    if new_condition == "CLOSED":
        # Cascade: cancel SCHEDULED/LOCKED departures on this trail. The trail
        # condition is set to CLOSED first so depart/lock gates see it, then the
        # cascade runs (departures consult their own state, not trail condition).
        trail["condition"] = "CLOSED"
        touch(trail)
        cancelled_count = svc.close_trail_cascade(trail)
    else:
        trail["condition"] = new_condition
        touch(trail)

    closure = stamp_lightweight_create({
        "trail_id": tid,
        "new_condition": new_condition,
        "reason": reason,
        "cancelled_departure_count": cancelled_count,
    })
    db.closure_events[closure["id"]] = closure
    return success(ser.closure_event_out(closure), 201)


@app.route("/trails/<tid>/closures", methods=["GET"])
def list_closures(tid):
    p = authenticate()
    authorize(p, {"DispatchOperator", "PlatformAdmin"})
    get_trail(tid)
    limit, offset = parse_pagination(request.args)
    items = [c for c in db.closure_events.values() if c["trail_id"] == tid]
    page, pmeta = paginate(items, limit, offset)
    return success([ser.closure_event_out(c) for c in page], 200, pagination=pmeta)


@app.route("/trails/<tid>/tour-departures", methods=["GET"])
def list_trail_departures(tid):
    p = authenticate()
    authorize(p, {"Member", "Guide", "DispatchOperator", "PlatformAdmin"})
    get_trail(tid)
    limit, offset = parse_pagination(request.args)
    items = [d for d in db.tour_departures.values() if d["trail_id"] == tid]
    status_filter = request.args.get("status")
    if status_filter is not None:
        items = [d for d in items if d["status"] == status_filter]
    page, pmeta = paginate(items, limit, offset)
    return success([ser.departure_out(d) for d in page], 200, pagination=pmeta)


# ===========================================================================
# Units
# ===========================================================================
@app.route("/units", methods=["POST"])
def create_unit():
    p = authenticate()
    authorize(p, {"DispatchOperator", "PlatformAdmin"})
    data = body()
    vin_tag = require_str(data, "vin_tag")
    unit_class = require_enum(data, "unit_class", CLASSES)
    daily_rate_cents = require_int(data, "daily_rate_cents", minimum=0)
    deposit_cents = require_int(data, "deposit_cents", minimum=0)
    tank_capacity_liters = require_number(data, "tank_capacity_liters", exclusive_min=0)

    for u in db.units.values():
        if u["vin_tag"] == vin_tag:
            err(ERR_DUPLICATE, "vin_tag already exists")

    unit = stamp_common_create({
        "vin_tag": vin_tag,
        "unit_class": unit_class,
        "daily_rate_cents": daily_rate_cents,
        "deposit_cents": deposit_cents,
        "tank_capacity_liters": tank_capacity_liters,
        "status": "AVAILABLE",
    })
    db.units[unit["id"]] = unit
    return success(ser.unit_out(unit), 201)


@app.route("/units/<uid>", methods=["GET"])
def fetch_unit(uid):
    p = authenticate()
    authorize(p, {"Member", "DispatchOperator", "PlatformAdmin"})
    unit = get_unit(uid)
    return success(ser.unit_out(unit), 200)


@app.route("/units/<uid>/maintenance", methods=["POST"])
def toggle_maintenance(uid):
    p = authenticate()
    authorize(p, {"DispatchOperator"})
    unit = get_unit(uid)
    data = body()
    return_to_service = data.get("return_to_service", False)
    if return_to_service is not None and not isinstance(return_to_service, bool):
        err(ERR_INVALID_REQUEST, "return_to_service must be a boolean")

    if return_to_service:
        # MAINTENANCE -> AVAILABLE.
        if unit["status"] != "MAINTENANCE":
            err(ERR_INVALID_STATE, "Unit is not in MAINTENANCE")
        unit["status"] = "AVAILABLE"
        touch(unit)
    else:
        # AVAILABLE -> MAINTENANCE.
        if unit["status"] != "AVAILABLE":
            err(ERR_INVALID_STATE, "Unit must be AVAILABLE to enter MAINTENANCE")
        unit["status"] = "MAINTENANCE"
        touch(unit)
    return success(ser.unit_out(unit), 200)


# ===========================================================================
# Gear
# ===========================================================================
@app.route("/gear-items", methods=["POST"])
def create_gear():
    p = authenticate()
    authorize(p, {"DispatchOperator", "PlatformAdmin"})
    data = body()
    kind = require_enum(data, "kind", {"HELMET", "SUIT"})
    size_code = require_str(data, "size_code")
    replacement_cost_cents = require_int(data, "replacement_cost_cents", minimum=0)
    gear = stamp_common_create({
        "kind": kind,
        "size_code": size_code,
        "replacement_cost_cents": replacement_cost_cents,
        "status": "AVAILABLE",
    })
    db.gear_items[gear["id"]] = gear
    return success(ser.gear_out(gear), 201)


@app.route("/gear-items/<gid>", methods=["GET"])
def fetch_gear(gid):
    p = authenticate()
    authorize(p, {"DispatchOperator", "PlatformAdmin"})
    gear = get_gear(gid)
    return success(ser.gear_out(gear), 200)


# ===========================================================================
# Tour Departures
# ===========================================================================
@app.route("/tour-departures", methods=["POST"])
def create_departure():
    p = authenticate()
    authorize(p, {"DispatchOperator"})
    data = body()
    trail_id = require_str(data, "trail_id")
    starts_at_dt = require_datetime(data, "starts_at")
    ends_at_dt = require_datetime(data, "ends_at")
    required_guide_class = require_enum(data, "required_guide_class", CLASSES)
    capacity_riders = require_int(data, "capacity_riders", minimum=1)
    if not (starts_at_dt < ends_at_dt):
        err(ERR_INVALID_REQUEST, "starts_at must be strictly before ends_at")
    # Existence: trail.
    get_trail(trail_id)

    departure = stamp_common_create({
        "trail_id": trail_id,
        "starts_at": data["starts_at"],
        "ends_at": data["ends_at"],
        "required_guide_class": required_guide_class,
        "capacity_riders": capacity_riders,
        "rider_count": 0,
        "guide_count": 0,
        "status": "SCHEDULED",
    })
    db.tour_departures[departure["id"]] = departure
    return success(ser.departure_out(departure), 201)


@app.route("/tour-departures/<did>", methods=["GET"])
def fetch_departure(did):
    p = authenticate()
    authorize(p, {"Member", "Guide", "DispatchOperator", "PlatformAdmin"})
    dep = get_departure(did)
    return success(ser.departure_out(dep), 200)


@app.route("/tour-departures/<did>/reservations", methods=["GET"])
def list_departure_reservations(did):
    p = authenticate()
    authorize(p, {"Guide", "DispatchOperator", "PlatformAdmin"})
    get_departure(did)
    limit, offset = parse_pagination(request.args)
    items = [r for r in db.reservations.values() if r["tour_departure_id"] == did]
    status_filter = request.args.get("reservation_status")
    if status_filter is not None:
        items = [r for r in items if r["reservation_status"] == status_filter]
    page, pmeta = paginate(items, limit, offset)
    return success([ser.reservation_out(r) for r in page], 200, pagination=pmeta)


@app.route("/tour-departures/<did>/guide-assignments", methods=["GET"])
def list_departure_guide_assignments(did):
    p = authenticate()
    authorize(p, {"Guide", "DispatchOperator", "PlatformAdmin"})
    get_departure(did)
    limit, offset = parse_pagination(request.args)
    items = [a for a in db.guide_assignments.values() if a["tour_departure_id"] == did]
    active_filter = _parse_bool_query("active")
    if active_filter is not None:
        items = [a for a in items if a["active"] == active_filter]
    page, pmeta = paginate(items, limit, offset)
    return success([ser.guide_assignment_out(a) for a in page], 200, pagination=pmeta)


@app.route("/tour-departures/<did>/assign-guide", methods=["POST"])
def assign_guide(did):
    p = authenticate()
    authorize(p, {"DispatchOperator"})
    dep = get_departure(did)
    data = body()
    guide_id = require_str(data, "guide_id")
    guide = get_guide(guide_id)

    # State gate: assignment is a side effect possible only while the departure
    # can still be staffed (SCHEDULED or LOCKED).
    if dep["status"] not in ("SCHEDULED", "LOCKED"):
        err(ERR_INVALID_STATE, "Cannot assign a guide to a departure in this state")

    # Guide double-booking (priority 14): half-open window overlap against any
    # other active assignment's departure window.
    if _guide_double_booked(guide, dep):
        err(ERR_GUIDE_DOUBLE_BOOKED, "Guide is assigned to an overlapping departure")

    # Class gate (priority 15).
    if class_rank(guide["max_class"]) < class_rank(dep["required_guide_class"]):
        err(ERR_GUIDE_CLASS_TOO_LOW, "Guide class is too low for this departure")

    assignment = stamp_lightweight_create({
        "tour_departure_id": did,
        "guide_id": guide_id,
        "active": True,
    })
    db.guide_assignments[assignment["id"]] = assignment

    if guide["status"] == "AVAILABLE":
        guide["status"] = "OFF_DUTY"
        touch(guide)
    dep["guide_count"] += 1
    touch(dep)
    return success(ser.guide_assignment_out(assignment), 201)


@app.route("/tour-departures/<did>/unassign-guide", methods=["POST"])
def unassign_guide(did):
    p = authenticate()
    authorize(p, {"DispatchOperator"})
    dep = get_departure(did)
    data = body()
    guide_id = require_str(data, "guide_id")
    guide = get_guide(guide_id)

    # Find an active assignment for this guide on this departure.
    target = None
    for a in db.guide_assignments.values():
        if a["tour_departure_id"] == did and a["guide_id"] == guide_id and a["active"]:
            target = a
            break
    if target is None:
        err(ERR_INVALID_STATE, "No active assignment for this guide on this departure")

    target["active"] = False
    dep["guide_count"] = max(0, dep["guide_count"] - 1)
    touch(dep)
    svc._maybe_return_guide_available(guide)
    return success(ser.departure_out(dep), 200)


@app.route("/tour-departures/<did>/lock", methods=["POST"])
def lock_departure(did):
    p = authenticate()
    authorize(p, {"DispatchOperator"})
    dep = get_departure(did)

    # State gate: lock defined only from SCHEDULED.
    if dep["status"] != "SCHEDULED":
        err(ERR_INVALID_STATE, "Departure can only be locked from SCHEDULED")

    # Guide ratio gate (priority 16): >= 1 rider AND guide_count >= required.
    required = calc.guide_ratio_required(dep["rider_count"])
    if dep["rider_count"] < 1 or dep["guide_count"] < required:
        err(ERR_GUIDE_RATIO_UNMET, "Guide ratio unmet or no riders")

    # Trail-closed gate (priority 17).
    trail = db.trails.get(dep["trail_id"])
    if trail is not None and trail["condition"] == "CLOSED":
        err(ERR_TRAIL_CLOSED, "Cannot lock a departure on a closed trail")

    dep["status"] = "LOCKED"
    touch(dep)
    return success(ser.departure_out(dep), 200)


@app.route("/tour-departures/<did>/depart", methods=["POST"])
def depart_departure(did):
    p = authenticate()
    authorize(p, {"Guide"})
    dep = get_departure(did)
    # Ownership (priority 3): guide must be assigned to this departure.
    if not _guide_assigned(p.user_id, did):
        err(ERR_OWNERSHIP_REQUIRED, "Guide is not assigned to this departure")

    # State gate: depart defined only from LOCKED.
    if dep["status"] != "LOCKED":
        err(ERR_INVALID_STATE, "Departure can only depart from LOCKED")

    # Trail-closed gate (priority 17).
    trail = db.trails.get(dep["trail_id"])
    if trail is not None and trail["condition"] == "CLOSED":
        err(ERR_TRAIL_CLOSED, "Cannot depart on a closed trail")

    # Clock must have reached starts_at.
    if clock.now() < parse_datetime(dep["starts_at"]):
        err(ERR_INVALID_STATE, "Cannot depart before starts_at")

    dep["status"] = "DEPARTED"
    touch(dep)

    # Cascade across this departure's reservations.
    for r in db.reservations.values():
        if r["tour_departure_id"] != did:
            continue
        if r["reservation_status"] == "CONFIRMED":
            _check_out_reservation(r)
        elif r["reservation_status"] == "PENDING":
            svc.cancel_reservation_internal(r)
    return success(ser.departure_out(dep), 200)


@app.route("/tour-departures/<did>/complete", methods=["POST"])
def complete_departure(did):
    p = authenticate()
    authorize(p, {"Guide"})
    dep = get_departure(did)
    if not _guide_assigned(p.user_id, did):
        err(ERR_OWNERSHIP_REQUIRED, "Guide is not assigned to this departure")

    # State gate: complete defined only from DEPARTED.
    if dep["status"] != "DEPARTED":
        err(ERR_INVALID_STATE, "Departure can only complete from DEPARTED")

    # Precondition: every CHECKED_OUT reservation has been resolved.
    for r in db.reservations.values():
        if r["tour_departure_id"] != did:
            continue
        if r["reservation_status"] == "CHECKED_OUT":
            err(ERR_INVALID_STATE, "All checked-out reservations must be returned or no-show")

    dep["status"] = "COMPLETED"
    svc.deactivate_departure_guides(dep)
    touch(dep)
    return success(ser.departure_out(dep), 200)


@app.route("/tour-departures/<did>/cancel", methods=["POST"])
def cancel_departure(did):
    p = authenticate()
    authorize(p, {"DispatchOperator"})
    dep = get_departure(did)
    # State gate: cancel defined only from SCHEDULED or LOCKED.
    if dep["status"] not in ("SCHEDULED", "LOCKED"):
        err(ERR_INVALID_STATE, "Departure can only be cancelled from SCHEDULED or LOCKED")
    svc.cancel_departure_internal(dep)
    return success(ser.departure_out(dep), 200)


# ===========================================================================
# Reservations
# ===========================================================================
@app.route("/reservations", methods=["POST"])
def create_reservation():
    p = authenticate()
    authorize(p, {"Member", "DispatchOperator"})
    data = body()
    member_id = require_str(data, "member_id")
    tour_departure_id = require_str(data, "tour_departure_id")
    unit_id = require_str(data, "unit_id")
    helmet_gear_id = data.get("helmet_gear_id")
    suit_gear_id = data.get("suit_gear_id")

    # Existence left-to-right: member, (trail via departure), unit, gear, departure.
    member = get_member(member_id)
    # Member ownership: a Member may only create a reservation for themselves.
    if p.role == "Member" and p.user_id != member_id:
        err(ERR_OWNERSHIP_REQUIRED, "Members may only create their own reservations")

    unit = get_unit(unit_id)
    if helmet_gear_id is not None:
        helmet = get_gear(helmet_gear_id)
    else:
        helmet = None
    if suit_gear_id is not None:
        suit = get_gear(suit_gear_id)
    else:
        suit = None
    dep = get_departure(tour_departure_id)

    # Gear kind/slot match (priority 5.1).
    if helmet is not None and helmet["kind"] != "HELMET":
        err(ERR_GEAR_KIND_MISMATCH, "helmet_gear_id must reference a HELMET")
    if suit is not None and suit["kind"] != "SUIT":
        err(ERR_GEAR_KIND_MISMATCH, "suit_gear_id must reference a SUIT")

    reservation = stamp_common_create({
        "member_id": member_id,
        "tour_departure_id": tour_departure_id,
        "unit_id": unit_id,
        "helmet_gear_id": helmet_gear_id,
        "suit_gear_id": suit_gear_id,
        "reservation_status": "PENDING",
        "settlement_status": "NONE",
        "estimated_total_cents": 0,
        "deposit_hold_cents": 0,
        "checked_out_at": None,
        "returned_at": None,
        "fuel_return_fraction": None,
    })
    db.reservations[reservation["id"]] = reservation
    return success(ser.reservation_out(reservation), 201)


@app.route("/reservations/<rid>", methods=["GET"])
def fetch_reservation(rid):
    p = authenticate()
    authorize(p, {"Member", "DispatchOperator", "PlatformAdmin"})
    res = get_reservation(rid)
    if p.role == "Member" and p.user_id != res["member_id"]:
        err(ERR_OWNERSHIP_REQUIRED, "Members may only access their own reservations")
    return success(ser.reservation_out(res), 200)


@app.route("/reservations", methods=["GET"])
def list_reservations():
    p = authenticate()
    authorize(p, {"DispatchOperator", "PlatformAdmin"})
    limit, offset = parse_pagination(request.args)
    items = list(db.reservations.values())
    for field in ("member_id", "tour_departure_id", "unit_id", "helmet_gear_id",
                  "suit_gear_id", "reservation_status"):
        val = request.args.get(field)
        if val is not None:
            items = [r for r in items if r.get(field) == val]
    page, pmeta = paginate(items, limit, offset)
    return success([ser.reservation_out(r) for r in page], 200, pagination=pmeta)


@app.route("/reservations/<rid>/confirm", methods=["POST"])
def confirm_reservation(rid):
    p = authenticate()
    authorize(p, {"Member", "DispatchOperator"})
    res = get_reservation(rid)
    # Ownership (priority 3) for entity-backed Member.
    if p.role == "Member" and p.user_id != res["member_id"]:
        err(ERR_OWNERSHIP_REQUIRED, "Members may only confirm their own reservations")

    data = body()
    # Body well-formedness (priority 5): expected_tour_departure_version required.
    expected_version = require_field(data, "expected_tour_departure_version")
    if isinstance(expected_version, bool) or not isinstance(expected_version, int):
        err(ERR_INVALID_REQUEST, "expected_tour_departure_version must be an integer")

    # State gate (priority 6): must be PENDING.
    if res["reservation_status"] != "PENDING":
        err(ERR_INVALID_STATE, "Reservation must be PENDING to confirm")

    member = db.members[res["member_id"]]
    dep = db.tour_departures[res["tour_departure_id"]]
    unit = db.units[res["unit_id"]]
    trail = db.trails[dep["trail_id"]]

    # Priority 7: departure must be SCHEDULED.
    if dep["status"] != "SCHEDULED":
        err(ERR_DEPARTURE_NOT_OPEN, "Departure is not open for confirmation")

    # Priority 8: waiver signed.
    if member["waiver_status"] != "SIGNED":
        err(ERR_WAIVER_NOT_SIGNED, "Member waiver is not signed")

    # Priority 9: age at starts_at >= MIN_RIDER_AGE.
    start_dt = parse_datetime(dep["starts_at"])
    if age_at(member["date_of_birth"], start_dt) < calc.MIN_RIDER_AGE:
        err(ERR_RIDER_UNDERAGE, "Rider is below the minimum riding age")

    # Priority 10: MOUNTAIN unit requires ADVANCED training.
    if unit["unit_class"] == "MOUNTAIN" and member["training_level"] != "ADVANCED":
        err(ERR_TRAINING_REQUIRED, "MOUNTAIN unit requires ADVANCED training")

    # Priority 11: unit class >= trail required class.
    if class_rank(unit["unit_class"]) < class_rank(trail["required_class"]):
        err(ERR_UNIT_CLASS_TOO_LOW, "Unit class is too low for the trail")

    # Priority 12: unit double-booking (half-open overlap).
    if _unit_double_booked(res, dep):
        err(ERR_UNIT_DOUBLE_BOOKED, "Unit is double-booked over an overlapping window")

    # Priority 13: gear double-booking (closed interval + buffer).
    if _gear_double_booked(res, dep):
        err(ERR_GEAR_DOUBLE_BOOKED, "Gear is double-booked over a buffered overlapping window")

    # Priority 18: capacity available.
    effective_cap = min(dep["capacity_riders"], trail["max_riders"])
    if dep["rider_count"] >= effective_cap:
        err(ERR_DEPARTURE_FULL, "Departure is at effective capacity")

    # Priority 19: OCC version match.
    if expected_version != dep["version"]:
        err(ERR_STALE_VERSION, "expected_tour_departure_version does not match")

    # --- All gates passed: commit side effects ---
    res["reservation_status"] = "CONFIRMED"
    res["settlement_status"] = "HELD"

    unit["status"] = "RESERVED"
    touch(unit)
    for gid in (res["helmet_gear_id"], res["suit_gear_id"]):
        if gid:
            gear = db.gear_items[gid]
            gear["status"] = "ASSIGNED"
            touch(gear)

    res["deposit_hold_cents"] = calc.deposit_hold(member, unit, clock.now())
    gear_count = sum(1 for gid in (res["helmet_gear_id"], res["suit_gear_id"]) if gid)
    res["estimated_total_cents"] = calc.estimate_reservation_quote(
        unit, trail, dep, member, gear_count, clock.now()
    )

    dep["rider_count"] += 1
    touch(dep)  # bumps version
    touch(res)

    svc.recompute_member_deposit_hold(member)
    return success(ser.reservation_out(res), 200)


@app.route("/reservations/<rid>/check-out", methods=["POST"])
def check_out_reservation(rid):
    p = authenticate()
    authorize(p, {"Guide", "DispatchOperator"})
    res = get_reservation(rid)
    dep = db.tour_departures.get(res["tour_departure_id"])

    # State gate: defined only from CONFIRMED.
    if res["reservation_status"] != "CONFIRMED":
        err(ERR_INVALID_STATE, "Reservation must be CONFIRMED to check out")

    # Precondition: departure LOCKED or DEPARTED, clock >= starts_at.
    if dep is None or dep["status"] not in ("LOCKED", "DEPARTED"):
        err(ERR_INVALID_STATE, "Departure must be LOCKED or DEPARTED to check out")
    if clock.now() < parse_datetime(dep["starts_at"]):
        err(ERR_INVALID_STATE, "Cannot check out before starts_at")

    _check_out_reservation(res)
    return success(ser.reservation_out(res), 200)


@app.route("/reservations/<rid>/return", methods=["POST"])
def return_reservation(rid):
    p = authenticate()
    authorize(p, {"DispatchOperator"})
    res = get_reservation(rid)
    data = body()

    # Existence of lost gear ids (left-to-right) is implicit; validate references.
    lost_gear_ids = data.get("lost_gear_ids", []) or []
    if not isinstance(lost_gear_ids, list):
        err(ERR_INVALID_REQUEST, "lost_gear_ids must be a list")

    # Body well-formedness: fuel_return_fraction required in [0,1] (priority 5.2).
    if "fuel_return_fraction" not in data or data["fuel_return_fraction"] is None:
        err(ERR_FUEL_FRACTION_REQUIRED, "fuel_return_fraction is required")
    frac = data["fuel_return_fraction"]
    if isinstance(frac, bool) or not isinstance(frac, (int, float)):
        err(ERR_FUEL_FRACTION_REQUIRED, "fuel_return_fraction must be a number in [0,1]")
    if frac < 0 or frac > 1:
        err(ERR_FUEL_FRACTION_REQUIRED, "fuel_return_fraction must be in [0,1]")

    damage = data.get("damage_assessed_cents", 0)
    if damage is None:
        damage = 0
    if isinstance(damage, bool) or not isinstance(damage, int) or damage < 0:
        err(ERR_INVALID_REQUEST, "damage_assessed_cents must be a non-negative integer")

    # State gate: defined only from CHECKED_OUT.
    if res["reservation_status"] != "CHECKED_OUT":
        err(ERR_INVALID_STATE, "Reservation must be CHECKED_OUT to return")

    # Duplicate settlement guard (priority 20).
    for s in db.settlements.values():
        if s["reservation_id"] == rid:
            err(ERR_DUPLICATE, "Reservation already settled")

    # Only gear actually assigned to this reservation can be flagged lost; any
    # other id is ignored (the gear-loss computation iterates the reservation's
    # own slots and checks membership in lost_gear_ids).
    lost_gear_ids = set(lost_gear_ids)

    unit = db.units[res["unit_id"]]
    dep = db.tour_departures[res["tour_departure_id"]]
    member = db.members[res["member_id"]]

    # Stamp return.
    res["returned_at"] = clock_iso()
    res["fuel_return_fraction"] = frac
    res["reservation_status"] = "RETURNED"
    res["settlement_status"] = "SETTLED"

    # Return unit.
    if unit["status"] == "OUT":
        unit["status"] = "AVAILABLE"
        touch(unit)

    # Return / retire gear.
    gear_loss_cents = 0
    for gid in (res["helmet_gear_id"], res["suit_gear_id"]):
        if not gid:
            continue
        gear = db.gear_items[gid]
        if gid in lost_gear_ids:
            gear["status"] = "RETIRED"
            gear_loss_cents += gear["replacement_cost_cents"]
            touch(gear)
        else:
            if gear["status"] == "OUT":
                gear["status"] = "AVAILABLE"
                touch(gear)

    # Compute settlement lines.
    rental_charge = res["estimated_total_cents"]
    fuel_charge = calc.fuel_charge(frac, unit["tank_capacity_liters"])
    late_charge = calc.late_charge(
        parse_datetime(res["returned_at"]), parse_datetime(dep["ends_at"])
    )
    waterfall = calc.final_settlement(
        rental_charge, fuel_charge, late_charge, damage, gear_loss_cents,
        res["deposit_hold_cents"],
    )

    settlement = stamp_common_create({
        "reservation_id": rid,
        "rental_charge_cents": rental_charge,
        "fuel_charge_cents": fuel_charge,
        "late_charge_cents": late_charge,
        "damage_assessed_cents": damage,
        "gear_loss_cents": gear_loss_cents,
        "deposit_applied_cents": waterfall["deposit_applied_cents"],
        "refund_cents": waterfall["refund_cents"],
        "net_charge_cents": waterfall["net_charge_cents"],
    })
    db.settlements[settlement["id"]] = settlement

    if damage > 0:
        member["lifetime_damage_strikes"] += 1
        touch(member)

    touch(res)
    svc.recompute_member_deposit_hold(member)
    return success(ser.settlement_out(settlement), 200)


@app.route("/reservations/<rid>/no-show", methods=["POST"])
def no_show_reservation(rid):
    p = authenticate()
    authorize(p, {"DispatchOperator"})
    res = get_reservation(rid)

    # State gate: defined only from CONFIRMED.
    if res["reservation_status"] != "CONFIRMED":
        err(ERR_INVALID_STATE, "Reservation must be CONFIRMED to mark no-show")

    dep = db.tour_departures[res["tour_departure_id"]]
    # Precondition: departure LOCKED or DEPARTED.
    if dep["status"] not in ("LOCKED", "DEPARTED"):
        err(ERR_INVALID_STATE, "Departure must be LOCKED or DEPARTED for no-show")

    # Duplicate settlement guard.
    for s in db.settlements.values():
        if s["reservation_id"] == rid:
            err(ERR_DUPLICATE, "Reservation already settled")

    member = db.members[res["member_id"]]
    unit = db.units[res["unit_id"]]

    # Release unit and gear.
    if unit["status"] == "RESERVED":
        unit["status"] = "AVAILABLE"
        touch(unit)
    for gid in (res["helmet_gear_id"], res["suit_gear_id"]):
        if gid:
            gear = db.gear_items[gid]
            if gear["status"] == "ASSIGNED":
                gear["status"] = "AVAILABLE"
                touch(gear)

    dep["rider_count"] = max(0, dep["rider_count"] - 1)
    touch(dep)

    res["reservation_status"] = "NO_SHOW"
    res["settlement_status"] = "SETTLED"

    settlement = stamp_common_create({
        "reservation_id": rid,
        "rental_charge_cents": calc.NO_SHOW_FEE_CENTS,
        "fuel_charge_cents": 0,
        "late_charge_cents": 0,
        "damage_assessed_cents": 0,
        "gear_loss_cents": 0,
        "deposit_applied_cents": 0,
        "refund_cents": res["deposit_hold_cents"],
        "net_charge_cents": calc.NO_SHOW_FEE_CENTS,
    })
    db.settlements[settlement["id"]] = settlement

    touch(res)
    svc.recompute_member_deposit_hold(member)
    return success(ser.settlement_out(settlement), 200)


@app.route("/reservations/<rid>/cancel", methods=["POST"])
def cancel_reservation(rid):
    p = authenticate()
    authorize(p, {"Member", "DispatchOperator"})
    res = get_reservation(rid)
    if p.role == "Member" and p.user_id != res["member_id"]:
        err(ERR_OWNERSHIP_REQUIRED, "Members may only cancel their own reservations")

    status = res["reservation_status"]
    # State gate: defined only from PENDING or CONFIRMED.
    if status not in ("PENDING", "CONFIRMED"):
        err(ERR_INVALID_STATE, "Reservation can only be cancelled from PENDING or CONFIRMED")

    # CONFIRMED cancel allowed only while departure not yet DEPARTED.
    if status == "CONFIRMED":
        dep = db.tour_departures.get(res["tour_departure_id"])
        if dep is not None and dep["status"] == "DEPARTED":
            err(ERR_INVALID_STATE, "Cannot cancel a confirmed reservation after departure")

    svc.cancel_reservation_internal(res)
    return success(ser.reservation_out(res), 200)


# ===========================================================================
# Settlements
# ===========================================================================
@app.route("/settlements/<sid>", methods=["GET"])
def fetch_settlement(sid):
    p = authenticate()
    authorize(p, {"Member", "DispatchOperator", "PlatformAdmin"})
    s = get_settlement(sid)
    if p.role == "Member":
        res = db.reservations.get(s["reservation_id"])
        if res is None or p.user_id != res["member_id"]:
            err(ERR_OWNERSHIP_REQUIRED, "Members may only access their own settlements")
    return success(ser.settlement_out(s), 200)


@app.route("/reservations/<rid>/settlement", methods=["GET"])
def fetch_reservation_settlement(rid):
    p = authenticate()
    authorize(p, {"Member", "DispatchOperator", "PlatformAdmin"})
    res = get_reservation(rid)
    if p.role == "Member" and p.user_id != res["member_id"]:
        err(ERR_OWNERSHIP_REQUIRED, "Members may only access their own settlements")
    items = [s for s in db.settlements.values() if s["reservation_id"] == rid]
    items_sorted = sorted(items, key=lambda r: r.get("_seq", 0))
    return success([ser.settlement_out(s) for s in items_sorted], 200)


# ===========================================================================
# Logical clock (test-driving)
# ===========================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    p = authenticate()
    authorize(p, {"PlatformAdmin"})
    data = body()
    to_iso = require_field(data, "to_iso8601")
    try:
        new_dt = parse_datetime(to_iso)
    except Exception:
        err(ERR_INVALID_REQUEST, "to_iso8601 must be an ISO 8601 datetime")
    clock.set(new_dt)
    # Re-evaluate waiver expiry across members.
    svc.reevaluate_all_waivers()
    return success({}, 200)


# ===========================================================================
# Internal helpers
# ===========================================================================
def _parse_bool_query(name):
    raw = request.args.get(name)
    if raw is None:
        return None
    low = raw.lower()
    if low in ("true", "1"):
        return True
    if low in ("false", "0"):
        return False
    err(ERR_INVALID_REQUEST, f"{name} must be a boolean")


def _check_out_reservation(res):
    """CONFIRMED -> CHECKED_OUT side effects (shared by depart cascade + check-out)."""
    res["reservation_status"] = "CHECKED_OUT"
    res["checked_out_at"] = clock_iso()
    unit = db.units.get(res["unit_id"])
    if unit and unit["status"] == "RESERVED":
        unit["status"] = "OUT"
        touch(unit)
    for gid in (res["helmet_gear_id"], res["suit_gear_id"]):
        if gid:
            gear = db.gear_items.get(gid)
            if gear and gear["status"] == "ASSIGNED":
                gear["status"] = "OUT"
                touch(gear)
    touch(res)


def _windows_overlap_half_open(a_start, a_end, b_start, b_end):
    """Half-open [start, end) overlap test."""
    return a_start < b_end and b_start < a_end


def _windows_overlap_closed(a_start, a_end, b_start, b_end):
    """Closed [start, end] overlap test."""
    return a_start <= b_end and b_start <= a_end


def _unit_double_booked(res, dep):
    """True if the chosen unit has another CONFIRMED/CHECKED_OUT reservation whose
    departure window (half-open) overlaps this departure's window."""
    this_start = parse_datetime(dep["starts_at"])
    this_end = parse_datetime(dep["ends_at"])
    unit_id = res["unit_id"]
    for other in db.reservations.values():
        if other["id"] == res["id"]:
            continue
        if other["unit_id"] != unit_id:
            continue
        if other["reservation_status"] not in ("CONFIRMED", "CHECKED_OUT"):
            continue
        odep = db.tour_departures.get(other["tour_departure_id"])
        if odep is None:
            continue
        o_start = parse_datetime(odep["starts_at"])
        o_end = parse_datetime(odep["ends_at"])
        if _windows_overlap_half_open(this_start, this_end, o_start, o_end):
            return True
    return False


def _gear_double_booked(res, dep):
    """True if either chosen gear item has another CONFIRMED/CHECKED_OUT reservation
    whose window (closed interval + GEAR_BUFFER_MINUTES on each side) overlaps."""
    from datetime import timedelta
    buf = timedelta(minutes=calc.GEAR_BUFFER_MINUTES)
    this_start = parse_datetime(dep["starts_at"]) - buf
    this_end = parse_datetime(dep["ends_at"]) + buf
    gear_ids = {g for g in (res["helmet_gear_id"], res["suit_gear_id"]) if g}
    if not gear_ids:
        return False
    for other in db.reservations.values():
        if other["id"] == res["id"]:
            continue
        if other["reservation_status"] not in ("CONFIRMED", "CHECKED_OUT"):
            continue
        other_gear = {g for g in (other["helmet_gear_id"], other["suit_gear_id"]) if g}
        if not (gear_ids & other_gear):
            continue
        odep = db.tour_departures.get(other["tour_departure_id"])
        if odep is None:
            continue
        o_start = parse_datetime(odep["starts_at"])
        o_end = parse_datetime(odep["ends_at"])
        if _windows_overlap_closed(this_start, this_end, o_start, o_end):
            return True
    return False


def _guide_double_booked(guide, dep):
    """True if the guide has another active assignment whose departure window
    (half-open) overlaps this departure's window."""
    this_start = parse_datetime(dep["starts_at"])
    this_end = parse_datetime(dep["ends_at"])
    for a in db.guide_assignments.values():
        if a["guide_id"] != guide["id"] or not a["active"]:
            continue
        if a["tour_departure_id"] == dep["id"]:
            continue
        odep = db.tour_departures.get(a["tour_departure_id"])
        if odep is None:
            continue
        o_start = parse_datetime(odep["starts_at"])
        o_end = parse_datetime(odep["ends_at"])
        if _windows_overlap_half_open(this_start, this_end, o_start, o_end):
            return True
    return False


def _guide_assigned(guide_id, departure_id):
    return any(
        a["guide_id"] == guide_id and a["tour_departure_id"] == departure_id and a["active"]
        for a in db.guide_assignments.values()
    )


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
