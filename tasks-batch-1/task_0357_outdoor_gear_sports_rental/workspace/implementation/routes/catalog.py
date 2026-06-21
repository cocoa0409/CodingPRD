"""Catalog endpoints: gear types, rate cards, season windows, add-ons.

Validation order (PRD §2.9): payload well-formedness (400) is checked BEFORE
authentication (401) and authorization (403).
"""
from flask import Blueprint, request

import db
import errors
import store
import serializers as S
import middleware as M
from response import ok, created, ok_list

bp = Blueprint("catalog", __name__)

CATEGORIES = {"KAYAK", "SKI", "SUP", "SNOWBOARD"}


# ---------------- GearType ----------------

@bp.post("/rental/gear-types")
def create_gear_type():
    body = M.get_json_body()
    # 0. payload well-formedness
    category = M.require_enum(body, "category", CATEGORIES)
    name = M.require_str(body, "name")
    size_label = M.require_str(body, "size_label")
    requires_lesson = M.optional_bool(body, "requires_lesson_for_beginner", False)
    active = M.optional_bool(body, "active", True)
    # 1-2. auth + role
    _, role = M.get_auth()
    M.require_role(role, {"ShopAdmin"})
    rec = store.create_gear_type(category, name, size_label, requires_lesson, active)
    return created(S.gear_type(rec))


@bp.get("/rental/gear-types/<id>")
def get_gear_type(id):
    _, role = M.get_auth()
    M.require_role(role, {"ShopAdmin", "RentalAgent", "Renter"})
    rec = db.gear_types.get(id)
    if not rec:
        raise errors.not_found("gear type not found")
    return ok(S.gear_type(rec))


@bp.get("/rental/gear-types")
def list_gear_types():
    _, role = M.get_auth()
    M.require_role(role, {"ShopAdmin", "RentalAgent", "Renter"})
    limit, offset = M.parse_pagination()
    items = list(db.gear_types.values())
    category = request.args.get("category")
    if category is not None:
        items = [r for r in items if r["category"] == category]
    page, total = store.paginate(items, limit, offset)
    return ok_list([S.gear_type(r) for r in page], limit, offset, total)


# ---------------- RateCard ----------------

@bp.post("/rental/rate-cards")
def create_rate_card():
    body = M.get_json_body()
    gear_type_id = M.require_str(body, "gear_type_id")
    hourly = M.require_int(body, "hourly_cents", 0)
    daily = M.require_int(body, "daily_cents", 0)
    seasonal = M.require_int(body, "seasonal_flat_cents", 0)
    deposit = M.require_int(body, "deposit_cents", 0)
    waiver = M.require_int(body, "damage_waiver_cents_per_day", 0)
    late = M.require_int(body, "late_fee_cents_per_hour", 0)
    loss = M.require_int(body, "loss_fee_cents", 0)
    grace = M.optional_int(body, "grace_minutes", 15, 0)
    active = M.optional_bool(body, "active", True)
    _, role = M.get_auth()
    M.require_role(role, {"ShopAdmin"})
    # existence (priority 4)
    if gear_type_id not in db.gear_types:
        raise errors.not_found("gear type not found")
    rec = store.create_rate_card(
        gear_type_id=gear_type_id, hourly_cents=hourly, daily_cents=daily,
        seasonal_flat_cents=seasonal, deposit_cents=deposit,
        damage_waiver_cents_per_day=waiver, late_fee_cents_per_hour=late,
        loss_fee_cents=loss, grace_minutes=grace, active=active,
    )
    return created(S.rate_card(rec))


@bp.get("/rental/rate-cards/<id>")
def get_rate_card(id):
    _, role = M.get_auth()
    M.require_role(role, {"ShopAdmin", "RentalAgent", "Renter"})
    rec = db.rate_cards.get(id)
    if not rec:
        raise errors.not_found("rate card not found")
    return ok(S.rate_card(rec))


@bp.get("/rental/rate-cards")
def list_rate_cards():
    _, role = M.get_auth()
    M.require_role(role, {"ShopAdmin", "RentalAgent", "Renter"})
    limit, offset = M.parse_pagination()
    items = list(db.rate_cards.values())
    gear_type_id = request.args.get("gear_type_id")
    if gear_type_id is not None:
        items = [r for r in items if r["gear_type_id"] == gear_type_id]
    page, total = store.paginate(items, limit, offset)
    return ok_list([S.rate_card(r) for r in page], limit, offset, total)


# ---------------- SeasonWindow ----------------

@bp.post("/rental/season-windows")
def create_season_window():
    body = M.get_json_body()
    category = M.require_enum(body, "category", CATEGORIES)
    label = M.require_str(body, "label")
    M.require_fields(body, ["starts_on", "ends_on", "demand_multiplier_bp"])
    starts_on = M.parse_dt(body["starts_on"], "starts_on")
    ends_on = M.parse_dt(body["ends_on"], "ends_on")
    mult = M.require_int(body, "demand_multiplier_bp", 1)
    _, role = M.get_auth()
    M.require_role(role, {"ShopAdmin"})
    rec = store.create_season_window(category, label, starts_on, ends_on, mult)
    return created(S.season_window(rec))


@bp.get("/rental/season-windows")
def list_season_windows():
    _, role = M.get_auth()
    M.require_role(role, {"ShopAdmin", "RentalAgent", "Renter"})
    limit, offset = M.parse_pagination()
    items = list(db.season_windows.values())
    category = request.args.get("category")
    if category is not None:
        items = [r for r in items if r["category"] == category]
    page, total = store.paginate(items, limit, offset)
    return ok_list([S.season_window(r) for r in page], limit, offset, total)


# ---------------- AddOn ----------------

@bp.post("/rental/addons")
def create_addon():
    body = M.get_json_body()
    kind = M.require_enum(body, "kind", {"LESSON", "PACKAGE"})
    category = M.require_enum(body, "category", CATEGORIES)
    name = M.require_str(body, "name")
    price = M.require_int(body, "price_cents", 0)
    capacity = M.optional_int(body, "capacity_per_slot", 1, 1)
    active = M.optional_bool(body, "active", True)
    _, role = M.get_auth()
    M.require_role(role, {"ShopAdmin"})
    rec = store.create_addon(kind, category, name, price, capacity, active)
    return created(S.addon(rec))


@bp.get("/rental/addons")
def list_addons():
    _, role = M.get_auth()
    M.require_role(role, {"ShopAdmin", "RentalAgent", "Renter"})
    limit, offset = M.parse_pagination()
    items = list(db.addons.values())
    category = request.args.get("category")
    if category is not None:
        items = [r for r in items if r["category"] == category]
    page, total = store.paginate(items, limit, offset)
    return ok_list([S.addon(r) for r in page], limit, offset, total)
