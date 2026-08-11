"""Configuration resources: SubscriptionPlan, Product, SeasonalWindow (PRD §3.2).
All are immutable after creation and carry only id + created_at."""
from flask import Blueprint

from db import new_id, serialize, stamp_new_config, store
from errors import fail
from middleware import authenticate, body, require_role
from response import ok
from services.pricing import window_ordinal_set
from util import req_enum, req_int, req_nonneg_int, req_pct, req_str, valid_md

bp = Blueprint("config", __name__)

ZONES = {"URBAN", "SUBURBAN", "RURAL"}
CATEGORIES = {"FEED", "BEDDING", "EGG_SUPPLIES", "HEALTH"}


@bp.route("/coopcare/subscription-plans", methods=["POST"])
def create_plan():
    uid, role = authenticate()
    require_role(role, {"PlatformAdmin"})
    data = body()
    plan_code = req_str(data, "plan_code")
    monthly_fee = req_nonneg_int(data, "monthly_fee_cents")
    incl_clean = req_nonneg_int(data, "included_cleanings_per_period")
    incl_health = req_nonneg_int(data, "included_health_checks_per_period")
    supply_pct = req_pct(data, "supply_discount_pct")
    sitting_pct = req_pct(data, "sitting_discount_pct")
    for p in store.plans.values():
        if p["plan_code"] == plan_code:
            fail("ERR_INVALID_REQUEST", "plan_code must be unique")
    rec = stamp_new_config({
        "id": new_id(),
        "plan_code": plan_code,
        "monthly_fee_cents": monthly_fee,
        "included_cleanings_per_period": incl_clean,
        "included_health_checks_per_period": incl_health,
        "supply_discount_pct": supply_pct,
        "sitting_discount_pct": sitting_pct,
    })
    store.plans[rec["id"]] = rec
    return ok(serialize(rec), 201)


@bp.route("/coopcare/products", methods=["POST"])
def create_product():
    uid, role = authenticate()
    require_role(role, {"PlatformAdmin"})
    data = body()
    sku = req_str(data, "sku")
    name = req_str(data, "name")
    category = req_enum(data, "category", CATEGORIES)
    unit_price = req_nonneg_int(data, "unit_price_cents")
    active = data.get("active", True)
    if not isinstance(active, bool):
        fail("ERR_INVALID_REQUEST", "active must be a boolean")
    for p in store.products.values():
        if p["sku"] == sku:
            fail("ERR_INVALID_REQUEST", "sku must be unique")
    rec = stamp_new_config({
        "id": new_id(),
        "sku": sku,
        "name": name,
        "category": category,
        "unit_price_cents": unit_price,
        "active": active,
    })
    store.products[rec["id"]] = rec
    return ok(serialize(rec), 201)


@bp.route("/coopcare/seasonal-windows", methods=["POST"])
def create_window():
    uid, role = authenticate()
    require_role(role, {"PlatformAdmin"})
    data = body()
    window_code = req_str(data, "window_code")
    zone_code = req_enum(data, "zone_code", ZONES)
    start_md = data.get("start_md")
    end_md = data.get("end_md")
    if not valid_md(start_md) or not valid_md(end_md):
        fail("ERR_INVALID_TIME_RANGE", "start_md and end_md must be well-formed MM-DD strings")
    visit_pct = req_pct(data, "visit_surcharge_pct")
    sitting_pct = req_pct(data, "sitting_surcharge_pct")
    for w in store.windows.values():
        if w["window_code"] == window_code:
            fail("ERR_INVALID_REQUEST", "window_code must be unique")
    new_days = window_ordinal_set({"start_md": start_md, "end_md": end_md})
    for w in store.windows.values():
        if w["zone_code"] != zone_code:
            continue
        if window_ordinal_set(w) & new_days:
            fail("ERR_SEASONAL_WINDOW_OVERLAP", "window covers a calendar day already covered for this zone")
    rec = stamp_new_config({
        "id": new_id(),
        "window_code": window_code,
        "zone_code": zone_code,
        "start_md": start_md,
        "end_md": end_md,
        "visit_surcharge_pct": visit_pct,
        "sitting_surcharge_pct": sitting_pct,
    })
    store.windows[rec["id"]] = rec
    return ok(serialize(rec), 201)
