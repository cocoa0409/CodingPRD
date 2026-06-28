"""Clock, health, and configuration-entity routes: style-services, add-ons,
membership-plans, chairs, stylists."""

from datetime import datetime, timezone

from flask import Blueprint, request

import errors
from common import (
    as_bool, as_enum, as_int, as_number, as_str, check_range, get_json_body,
    paginate, sort_by_created, stamp_new,
)
from db import db
from errors import err
from lookup import get_add_on, get_style_service
from middleware import get_auth, require_role
from response import success_list, success_object
from serialize import public, public_list

bp = Blueprint("config", __name__)

ALL_ROLES = {"FrontDesk", "FinanceManager", "Stylist", "Member"}


# ---------------------------------------------------------------------------
# Logical clock + health
# ---------------------------------------------------------------------------
@bp.post("/_clock/set_current_utc")
def set_clock():
    _, role = get_auth()
    require_role(role, {"FrontDesk", "FinanceManager"})
    body = get_json_body()
    iso = as_str(body, "to_iso8601")
    # Parse ISO 8601; accept trailing Z.
    raw = iso
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        raise err(errors.ERR_INVALID_REQUEST, "to_iso8601 is not a valid ISO 8601 instant")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    db.clock_utc = iso
    db.current_minute = dt.hour * 60 + dt.minute
    return success_object(
        {"current_utc": iso, "current_minute": db.current_minute}, 200
    )


@bp.get("/_health")
def health():
    return success_object({"status": "ok"}, 200)


# ---------------------------------------------------------------------------
# StyleService
# ---------------------------------------------------------------------------
@bp.post("/style-services")
def create_style_service():
    _, role = get_auth()
    require_role(role, {"FrontDesk"})
    body = get_json_body()
    name = as_str(body, "name")
    base_duration = as_int(body, "base_duration_minutes")
    base_price = as_int(body, "base_price_cents")
    blowout_credit_cost = as_int(body, "blowout_credit_cost", required=False, default=1)
    active = as_bool(body, "active", default=True)
    check_range("base_duration_minutes", base_duration, minimum=15, maximum=240, multiple_of=5)
    check_range("base_price_cents", base_price, minimum=0)
    check_range("blowout_credit_cost", blowout_credit_cost, minimum=0)
    svc = stamp_new({
        "name": name,
        "base_duration_minutes": base_duration,
        "base_price_cents": base_price,
        "blowout_credit_cost": blowout_credit_cost,
        "active": active,
    })
    db.style_services[svc["id"]] = svc
    return success_object(public(svc), 201)


@bp.get("/style-services")
def list_style_services():
    _, role = get_auth()
    require_role(role, ALL_ROLES)
    items = list(db.style_services.values())
    active = request.args.get("active")
    if active is not None:
        want = active.lower() == "true"
        items = [s for s in items if s["active"] == want]
    items = sort_by_created(items)
    page, limit, offset, total = paginate(items)
    return success_list(public_list(page), limit, offset, total, 200)


@bp.get("/style-services/<sid>")
def get_one_style_service(sid):
    _, role = get_auth()
    require_role(role, ALL_ROLES)
    svc = get_style_service(sid)
    return success_object(public(svc), 200)


# ---------------------------------------------------------------------------
# AddOn
# ---------------------------------------------------------------------------
@bp.post("/add-ons")
def create_add_on():
    _, role = get_auth()
    require_role(role, {"FrontDesk"})
    body = get_json_body()
    name = as_str(body, "name")
    category = as_enum(body, "category", {"UPDO", "BRAID", "EXTENSION"})
    extra_duration = as_int(body, "extra_duration_minutes")
    price = as_int(body, "price_cents")
    discount_eligible = as_bool(body, "discount_eligible", default=False)
    active = as_bool(body, "active", default=True)
    check_range("extra_duration_minutes", extra_duration, minimum=0, maximum=120, multiple_of=5)
    check_range("price_cents", price, minimum=0)
    addon = stamp_new({
        "name": name,
        "category": category,
        "extra_duration_minutes": extra_duration,
        "price_cents": price,
        "discount_eligible": discount_eligible,
        "active": active,
    })
    db.add_ons[addon["id"]] = addon
    return success_object(public(addon), 201)


@bp.get("/add-ons")
def list_add_ons():
    _, role = get_auth()
    require_role(role, ALL_ROLES)
    items = list(db.add_ons.values())
    category = request.args.get("category")
    if category is not None:
        items = [a for a in items if a["category"] == category]
    active = request.args.get("active")
    if active is not None:
        want = active.lower() == "true"
        items = [a for a in items if a["active"] == want]
    items = sort_by_created(items)
    page, limit, offset, total = paginate(items)
    return success_list(public_list(page), limit, offset, total, 200)


@bp.get("/add-ons/<aid>")
def get_one_add_on(aid):
    _, role = get_auth()
    require_role(role, ALL_ROLES)
    addon = get_add_on(aid)
    return success_object(public(addon), 200)


# ---------------------------------------------------------------------------
# MembershipPlan
# ---------------------------------------------------------------------------
@bp.post("/membership-plans")
def create_membership_plan():
    _, role = get_auth()
    require_role(role, {"FinanceManager"})
    body = get_json_body()
    tier = as_enum(body, "tier", {"BASIC", "PLUS", "VIP"})
    monthly_fee = as_int(body, "monthly_fee_cents")
    included_credits = as_int(body, "included_blowout_credits")
    discount_pct = as_number(body, "member_discount_pct")
    active = as_bool(body, "active", default=True)
    check_range("monthly_fee_cents", monthly_fee, minimum=0)
    check_range("included_blowout_credits", included_credits, minimum=0)
    if discount_pct < 0 or discount_pct > 1:
        raise err(errors.ERR_INVALID_REQUEST, "member_discount_pct must be between 0 and 1")
    plan = stamp_new({
        "tier": tier,
        "monthly_fee_cents": monthly_fee,
        "included_blowout_credits": included_credits,
        "member_discount_pct": discount_pct,
        "active": active,
    })
    db.membership_plans[plan["id"]] = plan
    return success_object(public(plan), 201)


@bp.get("/membership-plans")
def list_membership_plans():
    _, role = get_auth()
    require_role(role, ALL_ROLES)
    items = list(db.membership_plans.values())
    active = request.args.get("active")
    if active is not None:
        want = active.lower() == "true"
        items = [p for p in items if p["active"] == want]
    items = sort_by_created(items)
    page, limit, offset, total = paginate(items)
    return success_list(public_list(page), limit, offset, total, 200)


@bp.get("/membership-plans/<pid>")
def get_one_membership_plan(pid):
    _, role = get_auth()
    require_role(role, ALL_ROLES)
    plan = db.membership_plans.get(pid)
    if plan is None:
        # PRD §5 defines no plan-specific not-found id; a GET on a missing path id
        # still 404s with a descriptive id.
        from errors import ApiError
        raise ApiError("ERR_MEMBERSHIP_PLAN_NOT_FOUND", 404, "Membership plan not found")
    return success_object(public(plan), 200)


# ---------------------------------------------------------------------------
# Stylist
# ---------------------------------------------------------------------------
@bp.post("/stylists")
def create_stylist():
    _, role = get_auth()
    require_role(role, {"FrontDesk"})
    body = get_json_body()
    name = as_str(body, "full_name")
    tier = as_enum(body, "commission_tier", {"JUNIOR", "SENIOR", "MASTER"})
    shift_start = as_int(body, "shift_start_minute")
    shift_end = as_int(body, "shift_end_minute")
    active = as_bool(body, "active", default=True)
    check_range("shift_start_minute", shift_start, minimum=0, maximum=1439)
    if shift_end <= shift_start or shift_end > 1440:
        raise err(errors.ERR_INVALID_REQUEST, "shift_end_minute must be > shift_start_minute and <= 1440")
    stylist = stamp_new({
        "full_name": name,
        "commission_tier": tier,
        "shift_start_minute": shift_start,
        "shift_end_minute": shift_end,
        "earned_commission_cents": 0,
        "earned_tips_cents": 0,
        "active": active,
    })
    db.stylists[stylist["id"]] = stylist
    return success_object(public(stylist), 201)


@bp.get("/stylists")
def list_stylists():
    _, role = get_auth()
    require_role(role, ALL_ROLES)
    items = list(db.stylists.values())
    active = request.args.get("active")
    if active is not None:
        want = active.lower() == "true"
        items = [s for s in items if s["active"] == want]
    items = sort_by_created(items)
    page, limit, offset, total = paginate(items)
    return success_list(public_list(page), limit, offset, total, 200)


@bp.get("/stylists/<sid>")
def get_one_stylist(sid):
    _, role = get_auth()
    require_role(role, {"FrontDesk", "FinanceManager", "Stylist"})
    from lookup import get_stylist
    stylist = get_stylist(sid)
    return success_object(public(stylist), 200)


# ---------------------------------------------------------------------------
# Chair
# ---------------------------------------------------------------------------
@bp.post("/chairs")
def create_chair():
    _, role = get_auth()
    require_role(role, {"FrontDesk"})
    body = get_json_body()
    label = as_str(body, "label")
    open_minute = as_int(body, "open_minute")
    close_minute = as_int(body, "close_minute")
    buffer = as_int(body, "turnover_buffer_minutes", required=False, default=10)
    active = as_bool(body, "active", default=True)
    check_range("open_minute", open_minute, minimum=0, maximum=1439)
    if close_minute <= open_minute or close_minute > 1440:
        raise err(errors.ERR_INVALID_REQUEST, "close_minute must be > open_minute and <= 1440")
    check_range("turnover_buffer_minutes", buffer, minimum=0, maximum=60)
    chair = stamp_new({
        "label": label,
        "open_minute": open_minute,
        "close_minute": close_minute,
        "turnover_buffer_minutes": buffer,
        "active": active,
    })
    db.chairs[chair["id"]] = chair
    return success_object(public(chair), 201)


@bp.get("/chairs")
def list_chairs():
    _, role = get_auth()
    require_role(role, ALL_ROLES)
    items = list(db.chairs.values())
    active = request.args.get("active")
    if active is not None:
        want = active.lower() == "true"
        items = [c for c in items if c["active"] == want]
    items = sort_by_created(items)
    page, limit, offset, total = paginate(items)
    return success_list(public_list(page), limit, offset, total, 200)


@bp.get("/chairs/<cid>")
def get_one_chair(cid):
    _, role = get_auth()
    require_role(role, ALL_ROLES)
    from lookup import get_chair
    chair = get_chair(cid)
    return success_object(public(chair), 200)
