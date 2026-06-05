"""Configuration resources: Hotel, RoomType, Room (create/get/list/housekeeping),
RatePlan, CorporateAccount, Guest.
"""
from flask import Blueprint

import calc
import db
import helpers as H
import serialize as S
from errors import err
from middleware import authenticate, require_role
from response import success, success_list

bp = Blueprint("config", __name__)

ALL_ROLES = {"RevenueManager", "FrontDeskAgent", "NightAuditor", "Guest"}
NON_GUEST = {"RevenueManager", "FrontDeskAgent", "NightAuditor"}


# ----------------------------------------------------------------------------
# Hotel
# ----------------------------------------------------------------------------
@bp.route("/pms/hotels", methods=["POST"])
def create_hotel():
    _, role = authenticate()
    require_role(role, {"RevenueManager"})
    body = H.get_json_body()
    H.require_fields(body, ["name", "current_business_date"])
    name = H.require_str(body, "name")
    cbd = H.require_date(body, "current_business_date")

    timezone = body.get("timezone", "UTC")
    if timezone is None:
        timezone = "UTC"
    if not isinstance(timezone, str) or timezone == "":
        raise err("ERR_INVALID_REQUEST", "timezone must be a non-empty string")

    allowance = body.get("overbooking_allowance_pct", 0.0)
    if allowance is None:
        allowance = 0.0
    if isinstance(allowance, bool) or not isinstance(allowance, (int, float)):
        raise err("ERR_INVALID_REQUEST", "overbooking_allowance_pct must be a number")
    if allowance < 0.0 or allowance > 0.25:
        raise err("ERR_INVALID_REQUEST", "overbooking_allowance_pct must be within 0.0..0.25")

    h = {
        "name": name,
        "timezone": timezone,
        "current_business_date": cbd,
        "overbooking_allowance_pct": allowance,
        "audit_epoch": 0,
        "posture": "OPEN",
    }
    db.stamp_create(h)
    db.hotels[h["id"]] = h
    return success(S.hotel_out(h), status=201)


@bp.route("/pms/hotels/<resource_id>", methods=["GET"])
def get_hotel(resource_id):
    _, role = authenticate()
    require_role(role, ALL_ROLES)
    h = H.get_or_404(db.hotels, resource_id)
    return success(S.hotel_out(h), status=200)


# ----------------------------------------------------------------------------
# RoomType
# ----------------------------------------------------------------------------
@bp.route("/pms/room-types", methods=["POST"])
def create_room_type():
    _, role = authenticate()
    require_role(role, {"RevenueManager"})
    body = H.get_json_body()
    H.require_fields(body, ["hotel_id", "code", "tier_rank", "physical_inventory", "base_rate_cents"])
    H.resolve_fk(body, "hotel_id")
    code = H.require_str(body, "code")
    tier_rank = H.require_int(body, "tier_rank")
    if tier_rank < 1 or tier_rank > 99:
        raise err("ERR_INVALID_REQUEST", "tier_rank must be 1..99")
    physical_inventory = H.require_int(body, "physical_inventory", min_value=1)
    base_rate_cents = H.require_int(body, "base_rate_cents", min_value=0)

    # Unique code per hotel (PRD §2.10)
    for rt in db.room_types.values():
        if rt["hotel_id"] == body["hotel_id"] and rt["code"] == code:
            raise err("ERR_DUPLICATE_RESOURCE", "RoomType code already exists for this hotel")

    rt = {
        "hotel_id": body["hotel_id"],
        "code": code,
        "tier_rank": tier_rank,
        "physical_inventory": physical_inventory,
        "base_rate_cents": base_rate_cents,
    }
    db.stamp_create(rt)
    db.room_types[rt["id"]] = rt
    return success(S.room_type_out(rt), status=201)


@bp.route("/pms/room-types/<resource_id>", methods=["GET"])
def get_room_type(resource_id):
    _, role = authenticate()
    require_role(role, ALL_ROLES)
    rt = H.get_or_404(db.room_types, resource_id)
    return success(S.room_type_out(rt), status=200)


@bp.route("/pms/room-types", methods=["GET"])
def list_room_types():
    _, role = authenticate()
    require_role(role, ALL_ROLES)
    items, limit, offset, total = H.filter_and_paginate(
        db.room_types,
        S.room_type_out,
        {"hotel_id": H.qparam("hotel_id"), "code": H.qparam("code")},
    )
    return success_list(items, limit, offset, total)


# ----------------------------------------------------------------------------
# Room
# ----------------------------------------------------------------------------
@bp.route("/pms/rooms", methods=["POST"])
def create_room():
    _, role = authenticate()
    require_role(role, {"RevenueManager"})
    body = H.get_json_body()
    H.require_fields(body, ["hotel_id", "room_type_id", "room_number"])
    H.resolve_fk(body, "hotel_id")
    H.resolve_fk(body, "room_type_id")
    room_number = H.require_str(body, "room_number")

    for r in db.rooms.values():
        if r["hotel_id"] == body["hotel_id"] and r["room_number"] == room_number:
            raise err("ERR_DUPLICATE_RESOURCE", "Room number already exists for this hotel")

    r = {
        "hotel_id": body["hotel_id"],
        "room_type_id": body["room_type_id"],
        "room_number": room_number,
        "housekeeping_status": "CLEAN",
        "assigned_reservation_id": None,
    }
    db.stamp_create(r)
    db.rooms[r["id"]] = r
    return success(S.room_out(r), status=201)


@bp.route("/pms/rooms/<resource_id>", methods=["GET"])
def get_room(resource_id):
    _, role = authenticate()
    require_role(role, NON_GUEST)
    r = H.get_or_404(db.rooms, resource_id)
    return success(S.room_out(r), status=200)


@bp.route("/pms/rooms", methods=["GET"])
def list_rooms():
    _, role = authenticate()
    require_role(role, NON_GUEST)
    items, limit, offset, total = H.filter_and_paginate(
        db.rooms,
        S.room_out,
        {
            "hotel_id": H.qparam("hotel_id"),
            "room_type_id": H.qparam("room_type_id"),
            "assigned_reservation_id": H.qparam("assigned_reservation_id"),
            "housekeeping_status": H.qparam("housekeeping_status"),
        },
    )
    return success_list(items, limit, offset, total)


HOUSEKEEPING_TARGETS = {"DIRTY", "CLEAN", "INSPECTED", "OCCUPIED", "OUT_OF_ORDER"}


@bp.route("/pms/rooms/<resource_id>/housekeeping", methods=["POST"])
def room_housekeeping(resource_id):
    _, role = authenticate()
    require_role(role, {"FrontDeskAgent", "RevenueManager"})
    r = H.get_or_404(db.rooms, resource_id)
    body = H.get_json_body()
    H.require_fields(body, ["target", "expected_room_version"])
    target = body["target"]
    H.require_enum(target, HOUSEKEEPING_TARGETS, "target")
    expected = H.require_int(body, "expected_room_version")

    hotel = db.hotels[r["hotel_id"]]
    # posture gate (PRD §2.7 / §3.9)
    if hotel["posture"] != "OPEN":
        raise err("ERR_HOTEL_AUDIT_LOCKED", "Hotel is in AUDIT_LOCK posture")

    current = r["housekeeping_status"]

    # Determine the desk vs OOO transition map and actor permissions.
    # Desk (FrontDeskAgent or RevenueManager): DIRTY->CLEAN, CLEAN->INSPECTED.
    # OUT_OF_ORDER toggle reserved to RevenueManager: {DIRTY,CLEAN,INSPECTED}->OUT_OF_ORDER,
    # OUT_OF_ORDER->CLEAN.
    if target == "OUT_OF_ORDER":
        require_role(role, {"RevenueManager"})
        # transition validity
        if current not in ("DIRTY", "CLEAN", "INSPECTED"):
            raise err("ERR_INVALID_STATE", "Room not in a state that can go OUT_OF_ORDER")
        # OCC after state validity per §3.9 ordering (OCC last)
        if expected != r["version"]:
            raise err("ERR_STALE_ROOM_VERSION", "expected_room_version does not match Room.version")
        if r["assigned_reservation_id"] is not None:
            raise err("ERR_ROOM_NOT_ASSIGNABLE", "Room bound to a reservation cannot go OUT_OF_ORDER")
        r["housekeeping_status"] = "OUT_OF_ORDER"
        db.touch(r)
        return success(S.room_out(r), status=200)

    if current == "OUT_OF_ORDER" and target == "CLEAN":
        require_role(role, {"RevenueManager"})
        if expected != r["version"]:
            raise err("ERR_STALE_ROOM_VERSION", "expected_room_version does not match Room.version")
        r["housekeeping_status"] = "CLEAN"
        db.touch(r)
        return success(S.room_out(r), status=200)

    # Desk-driven cycle transitions.
    desk_transitions = {("DIRTY", "CLEAN"), ("CLEAN", "INSPECTED")}
    if (current, target) in desk_transitions:
        if expected != r["version"]:
            raise err("ERR_STALE_ROOM_VERSION", "expected_room_version does not match Room.version")
        r["housekeeping_status"] = target
        db.touch(r)
        return success(S.room_out(r), status=200)

    # Anything else is an invalid transition (incl. INSPECTED->OCCUPIED and
    # OCCUPIED->DIRTY, which are system-only at check-in/check-out).
    raise err("ERR_INVALID_STATE", "Invalid housekeeping transition")


# ----------------------------------------------------------------------------
# RatePlan
# ----------------------------------------------------------------------------
RATE_PLAN_KINDS = {"BAR", "CORPORATE", "PACKAGE"}
ADJUSTMENT_MODES = {"PCT", "FLAT"}
NO_SHOW_POLICIES = {"FIRST_NIGHT", "FULL_STAY", "NONE"}


@bp.route("/pms/rate-plans", methods=["POST"])
def create_rate_plan():
    _, role = authenticate()
    require_role(role, {"RevenueManager"})
    body = H.get_json_body()
    H.require_fields(body, ["hotel_id", "code", "kind", "adjustment_mode", "adjustment_value", "no_show_policy"])
    H.resolve_fk(body, "hotel_id")
    code = H.require_str(body, "code")
    kind = body["kind"]
    H.require_enum(kind, RATE_PLAN_KINDS, "kind")
    adjustment_mode = body["adjustment_mode"]
    H.require_enum(adjustment_mode, ADJUSTMENT_MODES, "adjustment_mode")
    adjustment_value = H.require_int(body, "adjustment_value")
    no_show_policy = body["no_show_policy"]
    H.require_enum(no_show_policy, NO_SHOW_POLICIES, "no_show_policy")

    corporate_account_id = body.get("corporate_account_id")
    if kind == "CORPORATE":
        if corporate_account_id is None:
            raise err("ERR_INVALID_REQUEST", "corporate_account_id required when kind=CORPORATE")
        H.resolve_fk(body, "corporate_account_id")
    else:
        corporate_account_id = None

    package_fee_cents = body.get("package_fee_cents", 0)
    if package_fee_cents is None:
        package_fee_cents = 0
    if isinstance(package_fee_cents, bool) or not isinstance(package_fee_cents, int):
        raise err("ERR_INVALID_REQUEST", "package_fee_cents must be an integer")
    if package_fee_cents < 0:
        raise err("ERR_INVALID_REQUEST", "package_fee_cents must be >= 0")
    if kind != "PACKAGE":
        package_fee_cents = 0

    for rp in db.rate_plans.values():
        if rp["hotel_id"] == body["hotel_id"] and rp["code"] == code:
            raise err("ERR_DUPLICATE_RESOURCE", "RatePlan code already exists for this hotel")

    rp = {
        "hotel_id": body["hotel_id"],
        "code": code,
        "kind": kind,
        "corporate_account_id": corporate_account_id,
        "adjustment_mode": adjustment_mode,
        "adjustment_value": adjustment_value,
        "package_fee_cents": package_fee_cents,
        "no_show_policy": no_show_policy,
        "status": "ACTIVE",
    }
    db.stamp_create(rp)
    db.rate_plans[rp["id"]] = rp
    return success(S.rate_plan_out(rp), status=201)


@bp.route("/pms/rate-plans/<resource_id>", methods=["GET"])
def get_rate_plan(resource_id):
    _, role = authenticate()
    require_role(role, ALL_ROLES)
    rp = H.get_or_404(db.rate_plans, resource_id)
    return success(S.rate_plan_out(rp), status=200)


@bp.route("/pms/rate-plans", methods=["GET"])
def list_rate_plans():
    _, role = authenticate()
    require_role(role, ALL_ROLES)
    items, limit, offset, total = H.filter_and_paginate(
        db.rate_plans,
        S.rate_plan_out,
        {
            "hotel_id": H.qparam("hotel_id"),
            "corporate_account_id": H.qparam("corporate_account_id"),
            "kind": H.qparam("kind"),
            "status": H.qparam("status"),
        },
    )
    return success_list(items, limit, offset, total)


@bp.route("/pms/rate-plans/<resource_id>/close", methods=["POST"])
def close_rate_plan(resource_id):
    _, role = authenticate()
    require_role(role, {"RevenueManager"})
    rp = H.get_or_404(db.rate_plans, resource_id)
    body = H.get_json_body()
    H.require_fields(body, ["expected_rate_plan_version"])
    expected = H.require_int(body, "expected_rate_plan_version")
    if rp["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Rate plan is not ACTIVE")
    if expected != rp["version"]:
        raise err("ERR_STALE_VERSION", "expected_rate_plan_version does not match")
    rp["status"] = "CLOSED"
    db.touch(rp)
    return success(S.rate_plan_out(rp), status=200)


# ----------------------------------------------------------------------------
# CorporateAccount
# ----------------------------------------------------------------------------
@bp.route("/pms/corporate-accounts", methods=["POST"])
def create_corporate_account():
    _, role = authenticate()
    require_role(role, {"RevenueManager"})
    body = H.get_json_body()
    H.require_fields(body, ["hotel_id", "name", "credit_limit_cents"])
    H.resolve_fk(body, "hotel_id")
    name = H.require_str(body, "name")
    credit_limit_cents = H.require_int(body, "credit_limit_cents", min_value=0)

    ca = {
        "hotel_id": body["hotel_id"],
        "name": name,
        "credit_limit_cents": credit_limit_cents,
        "status": "ACTIVE",
    }
    db.stamp_create(ca)
    db.corporate_accounts[ca["id"]] = ca
    return success(S.corporate_account_out(ca), status=201)


@bp.route("/pms/corporate-accounts/<resource_id>", methods=["GET"])
def get_corporate_account(resource_id):
    _, role = authenticate()
    require_role(role, NON_GUEST)
    ca = H.get_or_404(db.corporate_accounts, resource_id)
    return success(S.corporate_account_out(ca), status=200)


@bp.route("/pms/corporate-accounts", methods=["GET"])
def list_corporate_accounts():
    _, role = authenticate()
    require_role(role, NON_GUEST)
    items, limit, offset, total = H.filter_and_paginate(
        db.corporate_accounts,
        S.corporate_account_out,
        {"hotel_id": H.qparam("hotel_id"), "status": H.qparam("status")},
    )
    return success_list(items, limit, offset, total)


@bp.route("/pms/corporate-accounts/<resource_id>/suspend", methods=["POST"])
def suspend_corporate_account(resource_id):
    _, role = authenticate()
    require_role(role, {"RevenueManager"})
    ca = H.get_or_404(db.corporate_accounts, resource_id)
    body = H.get_json_body()
    H.require_fields(body, ["expected_corporate_account_version"])
    expected = H.require_int(body, "expected_corporate_account_version")
    if ca["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Account is not ACTIVE")
    if expected != ca["version"]:
        raise err("ERR_STALE_VERSION", "expected_corporate_account_version does not match")
    ca["status"] = "SUSPENDED"
    db.touch(ca)
    return success(S.corporate_account_out(ca), status=200)


@bp.route("/pms/corporate-accounts/<resource_id>/reinstate", methods=["POST"])
def reinstate_corporate_account(resource_id):
    _, role = authenticate()
    require_role(role, {"RevenueManager"})
    ca = H.get_or_404(db.corporate_accounts, resource_id)
    body = H.get_json_body()
    H.require_fields(body, ["expected_corporate_account_version"])
    expected = H.require_int(body, "expected_corporate_account_version")
    if ca["status"] != "SUSPENDED":
        raise err("ERR_INVALID_STATE", "Account is not SUSPENDED")
    if expected != ca["version"]:
        raise err("ERR_STALE_VERSION", "expected_corporate_account_version does not match")
    ca["status"] = "ACTIVE"
    db.touch(ca)
    return success(S.corporate_account_out(ca), status=200)


# ----------------------------------------------------------------------------
# Guest
# ----------------------------------------------------------------------------
LOYALTY_TIERS = {"NONE", "SILVER", "GOLD", "PLATINUM"}


@bp.route("/pms/guests", methods=["POST"])
def create_guest():
    _, role = authenticate()
    require_role(role, {"FrontDeskAgent", "RevenueManager"})
    body = H.get_json_body()
    H.require_fields(body, ["hotel_id", "full_name", "email"])
    H.resolve_fk(body, "hotel_id")
    full_name = H.require_str(body, "full_name")
    email = H.require_str(body, "email")
    loyalty_tier = body.get("loyalty_tier", "NONE")
    if loyalty_tier is None:
        loyalty_tier = "NONE"
    H.require_enum(loyalty_tier, LOYALTY_TIERS, "loyalty_tier")

    for g in db.guests.values():
        if g["hotel_id"] == body["hotel_id"] and g["email"] == email:
            raise err("ERR_DUPLICATE_RESOURCE", "Guest email already exists for this hotel")

    g = {
        "hotel_id": body["hotel_id"],
        "full_name": full_name,
        "email": email,
        "loyalty_tier": loyalty_tier,
    }
    db.stamp_create(g)
    db.guests[g["id"]] = g
    return success(S.guest_out(g), status=201)


@bp.route("/pms/guests/<resource_id>", methods=["GET"])
def get_guest(resource_id):
    user_id, role = authenticate()
    require_role(role, ALL_ROLES)
    g = H.get_or_404(db.guests, resource_id)
    # Guest may read only their own guest record (PRD §2.1)
    if role == "Guest" and g["id"] != user_id:
        raise err("ERR_FORBIDDEN", "Guest may only read their own data")
    return success(S.guest_out(g), status=200)


@bp.route("/pms/guests", methods=["GET"])
def list_guests():
    _, role = authenticate()
    require_role(role, NON_GUEST)
    items, limit, offset, total = H.filter_and_paginate(
        db.guests,
        S.guest_out,
        {"hotel_id": H.qparam("hotel_id"), "email": H.qparam("email")},
    )
    return success_list(items, limit, offset, total)
