"""Catalog & configuration routes: customers, zones, arrangements,
holiday windows, florists (PRD §3.1)."""
from flask import Blueprint

import errors
from db import store
from middleware import require_auth, require_role
from helpers import (
    get_body, make_record, touch, public, parse_pagination, paginate,
    require_fields, as_int, as_str, as_bool, as_number, as_enum,
)
from response import success, success_list
from services import clock

bp = Blueprint("catalog", __name__)


# ===========================================================================
# Customers
# ===========================================================================
@bp.route("/floral/customers", methods=["POST"])
def create_customer():
    _, role = require_auth()
    require_role(role, {"CatalogAdmin", "Dispatcher"})
    body = get_body()
    require_fields(body, ["email", "full_name"])
    email = as_str(body, "email")
    full_name = as_str(body, "full_name")
    if email.strip() == "":
        raise errors.invalid_request("email must be non-empty")
    # email unique across customers
    for c in store.customers.values():
        if c["email"] == email:
            raise errors.invalid_request("email already in use")
    rec = make_record()
    rec.update({
        "email": email,
        "full_name": full_name,
        "loyalty_tier": "STANDARD",
        "lifetime_delivered_count": 0,
        "wallet_credit_cents": 0,
    })
    store.customers[rec["id"]] = rec
    return success(public(rec), status=201)


@bp.route("/floral/customers/<cid>", methods=["GET"])
def get_customer(cid):
    _, role = require_auth()
    require_role(role, {"CatalogAdmin", "Dispatcher", "Customer"})
    rec = store.customers.get(cid)
    if rec is None:
        raise errors.not_found("Customer not found")
    return success(public(rec))


@bp.route("/floral/customers", methods=["GET"])
def list_customers():
    _, role = require_auth()
    require_role(role, {"CatalogAdmin", "Dispatcher"})
    limit, offset = parse_pagination()
    page, total = paginate(list(store.customers.values()), limit, offset)
    return success_list([public(r) for r in page], limit, offset, total)


# ===========================================================================
# Zones
# ===========================================================================
@bp.route("/floral/zones", methods=["POST"])
def create_zone():
    _, role = require_auth()
    require_role(role, {"CatalogAdmin"})
    body = get_body()
    require_fields(body, ["zone_code", "base_delivery_fee_cents",
                          "same_day_cutoff_hour_utc", "window_capacity_per_slot"])
    zone_code = as_str(body, "zone_code")
    if zone_code.strip() == "":
        raise errors.invalid_request("zone_code must be non-empty")
    fee = as_int(body, "base_delivery_fee_cents")
    cutoff = as_int(body, "same_day_cutoff_hour_utc")
    capacity = as_int(body, "window_capacity_per_slot")
    active = as_bool(body, "active", default=True)
    if fee < 0:
        raise errors.validation_range("base_delivery_fee_cents must be >= 0")
    if cutoff < 0 or cutoff > 23:
        raise errors.validation_range("same_day_cutoff_hour_utc must be 0..23")
    if capacity < 1:
        raise errors.validation_range("window_capacity_per_slot must be >= 1")
    for z in store.zones.values():
        if z["zone_code"] == zone_code:
            raise errors.invalid_request("zone_code already in use")
    rec = make_record()
    rec.update({
        "zone_code": zone_code,
        "base_delivery_fee_cents": fee,
        "same_day_cutoff_hour_utc": cutoff,
        "window_capacity_per_slot": capacity,
        "active": active,
    })
    store.zones[rec["id"]] = rec
    return success(public(rec), status=201)


@bp.route("/floral/zones/<zid>", methods=["GET"])
def get_zone(zid):
    _, role = require_auth()
    require_role(role, {"CatalogAdmin", "Dispatcher", "Customer", "Florist"})
    rec = store.zones.get(zid)
    if rec is None:
        raise errors.not_found("Zone not found")
    return success(public(rec))


@bp.route("/floral/zones", methods=["GET"])
def list_zones():
    _, role = require_auth()
    require_role(role, {"CatalogAdmin", "Dispatcher", "Customer", "Florist"})
    limit, offset = parse_pagination()
    page, total = paginate(list(store.zones.values()), limit, offset)
    return success_list([public(r) for r in page], limit, offset, total)


# ===========================================================================
# Arrangements
# ===========================================================================
@bp.route("/floral/arrangements", methods=["POST"])
def create_arrangement():
    _, role = require_auth()
    require_role(role, {"CatalogAdmin"})
    body = get_body()
    require_fields(body, ["sku", "display_name", "base_price_cents"])
    sku = as_str(body, "sku")
    if sku.strip() == "":
        raise errors.invalid_request("sku must be non-empty")
    display_name = as_str(body, "display_name")
    base_price = as_int(body, "base_price_cents")
    premium_tier = as_enum(body, "premium_tier", {"STANDARD", "PREMIUM"},
                           required=False, default="STANDARD")
    substitution_policy = as_enum(
        body, "substitution_policy", {"NONE", "SAME_VALUE", "FLORIST_CHOICE"},
        required=False, default="SAME_VALUE")
    substitution_cap_pct = as_number(body, "substitution_cap_pct",
                                     required=False, default=0.15)
    active = as_bool(body, "active", default=True)
    if base_price < 0:
        raise errors.validation_range("base_price_cents must be >= 0")
    if substitution_cap_pct < 0 or substitution_cap_pct > 1:
        raise errors.validation_range("substitution_cap_pct must be 0..1")
    for a in store.arrangements.values():
        if a["sku"] == sku:
            raise errors.invalid_request("sku already in use")
    rec = make_record()
    rec.update({
        "sku": sku,
        "display_name": display_name,
        "base_price_cents": base_price,
        "premium_tier": premium_tier,
        "substitution_policy": substitution_policy,
        "substitution_cap_pct": substitution_cap_pct,
        "active": active,
    })
    store.arrangements[rec["id"]] = rec
    return success(public(rec), status=201)


@bp.route("/floral/arrangements/<aid>", methods=["GET"])
def get_arrangement(aid):
    _, role = require_auth()
    require_role(role, {"CatalogAdmin", "Dispatcher", "Customer", "Florist"})
    rec = store.arrangements.get(aid)
    if rec is None:
        raise errors.not_found("Arrangement not found")
    return success(public(rec))


@bp.route("/floral/arrangements", methods=["GET"])
def list_arrangements():
    _, role = require_auth()
    require_role(role, {"CatalogAdmin", "Dispatcher", "Customer", "Florist"})
    limit, offset = parse_pagination()
    page, total = paginate(list(store.arrangements.values()), limit, offset)
    return success_list([public(r) for r in page], limit, offset, total)


# ===========================================================================
# Holiday windows
# ===========================================================================
@bp.route("/floral/holiday-windows", methods=["POST"])
def create_holiday_window():
    _, role = require_auth()
    require_role(role, {"CatalogAdmin"})
    body = get_body()
    require_fields(body, ["name", "start_date", "end_date", "surge_multiplier",
                          "surge_cutoff_hour_utc"])
    name = as_str(body, "name")
    if name.strip() == "":
        raise errors.invalid_request("name must be non-empty")
    start_date = as_str(body, "start_date")
    end_date = as_str(body, "end_date")
    clock.parse_date(start_date)
    clock.parse_date(end_date)
    surge_multiplier = as_number(body, "surge_multiplier")
    applies_to_standard = as_bool(body, "applies_to_standard", default=False)
    surge_cutoff = as_int(body, "surge_cutoff_hour_utc")
    if surge_multiplier <= 1.0:
        raise errors.validation_range("surge_multiplier must be > 1.0")
    if surge_cutoff < 0 or surge_cutoff > 23:
        raise errors.validation_range("surge_cutoff_hour_utc must be 0..23")
    for w in store.holiday_windows.values():
        if w["name"] == name:
            raise errors.invalid_request("holiday window name already in use")
    rec = make_record()
    rec.update({
        "name": name,
        "start_date": start_date,
        "end_date": end_date,
        "surge_multiplier": surge_multiplier,
        "applies_to_standard": applies_to_standard,
        "surge_cutoff_hour_utc": surge_cutoff,
    })
    store.holiday_windows[rec["id"]] = rec
    return success(public(rec), status=201)


@bp.route("/floral/holiday-windows/<wid>", methods=["GET"])
def get_holiday_window(wid):
    _, role = require_auth()
    require_role(role, {"CatalogAdmin", "Dispatcher"})
    rec = store.holiday_windows.get(wid)
    if rec is None:
        raise errors.not_found("Holiday window not found")
    return success(public(rec))


@bp.route("/floral/holiday-windows", methods=["GET"])
def list_holiday_windows():
    _, role = require_auth()
    require_role(role, {"CatalogAdmin", "Dispatcher"})
    limit, offset = parse_pagination()
    page, total = paginate(list(store.holiday_windows.values()), limit, offset)
    return success_list([public(r) for r in page], limit, offset, total)


# ===========================================================================
# Florists
# ===========================================================================
@bp.route("/floral/florists", methods=["POST"])
def create_florist():
    _, role = require_auth()
    require_role(role, {"Dispatcher"})
    body = get_body()
    require_fields(body, ["shop_name", "covered_zone_id", "daily_capacity"])
    shop_name = as_str(body, "shop_name")
    covered_zone_id = as_str(body, "covered_zone_id")
    daily_capacity = as_int(body, "daily_capacity")
    quality_rating = as_number(body, "quality_rating", required=False, default=4.0)
    wire_surcharge_cents = as_int(body, "wire_surcharge_cents",
                                  required=False, default=0)
    accepting = as_bool(body, "accepting", default=True)
    if daily_capacity < 1:
        raise errors.validation_range("daily_capacity must be >= 1")
    if quality_rating < 0.0 or quality_rating > 5.0:
        raise errors.validation_range("quality_rating must be 0.0..5.0")
    if wire_surcharge_cents < 0:
        raise errors.validation_range("wire_surcharge_cents must be >= 0")
    # FK existence: covered_zone_id must resolve.
    if covered_zone_id not in store.zones:
        raise errors.not_found("covered_zone_id not found")
    rec = make_record()
    rec.update({
        "shop_name": shop_name,
        "covered_zone_id": covered_zone_id,
        "daily_capacity": daily_capacity,
        "quality_rating": quality_rating,
        "wire_surcharge_cents": wire_surcharge_cents,
        "accepting": accepting,
    })
    store.florists[rec["id"]] = rec
    return success(public(rec), status=201)


@bp.route("/floral/florists/<fid>", methods=["GET"])
def get_florist(fid):
    _, role = require_auth()
    require_role(role, {"Dispatcher", "Florist", "CatalogAdmin"})
    rec = store.florists.get(fid)
    if rec is None:
        raise errors.not_found("Florist not found")
    return success(public(rec))


@bp.route("/floral/florists", methods=["GET"])
def list_florists():
    _, role = require_auth()
    require_role(role, {"Dispatcher", "Florist", "CatalogAdmin"})
    limit, offset = parse_pagination()
    from flask import request
    rows = list(store.florists.values())
    covered_zone_id = request.args.get("covered_zone_id")
    if covered_zone_id is not None:
        rows = [r for r in rows if r["covered_zone_id"] == covered_zone_id]
    page, total = paginate(rows, limit, offset)
    return success_list([public(r) for r in page], limit, offset, total)


@bp.route("/floral/florists/<fid>", methods=["PATCH"])
def update_florist(fid):
    _, role = require_auth()
    require_role(role, {"Dispatcher"})
    rec = store.florists.get(fid)
    if rec is None:
        raise errors.not_found("Florist not found")
    body = get_body()
    if "accepting" in body and body["accepting"] is not None:
        rec["accepting"] = as_bool(body, "accepting")
    if "quality_rating" in body and body["quality_rating"] is not None:
        qr = as_number(body, "quality_rating")
        if qr < 0.0 or qr > 5.0:
            raise errors.validation_range("quality_rating must be 0.0..5.0")
        rec["quality_rating"] = qr
    if "wire_surcharge_cents" in body and body["wire_surcharge_cents"] is not None:
        ws = as_int(body, "wire_surcharge_cents")
        if ws < 0:
            raise errors.validation_range("wire_surcharge_cents must be >= 0")
        rec["wire_surcharge_cents"] = ws
    if "daily_capacity" in body and body["daily_capacity"] is not None:
        dc = as_int(body, "daily_capacity")
        if dc < 1:
            raise errors.validation_range("daily_capacity must be >= 1")
        rec["daily_capacity"] = dc
    touch(rec)
    return success(public(rec))
