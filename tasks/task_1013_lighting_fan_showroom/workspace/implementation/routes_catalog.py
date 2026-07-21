"""Catalog & shared-resource config: trade-accounts, fixture-models, installers,
delivery-trucks, rebate-programs, and the logical clock."""
from flask import Blueprint

import serializers
from auth import require
from envelope import ok, created, ok_empty
from errors import err
from listing import list_response
from store import db, new_base, insert, touch, fetch
from validation import (
    get_body,
    req_str,
    opt_str,
    req_int,
    opt_int,
    req_number,
    req_bool_default,
    req_enum,
    opt_enum,
    req_datetime,
)

bp = Blueprint("catalog", __name__)

CATEGORIES = {"CEILING_FAN", "CHANDELIER", "PENDANT", "SCONCE", "RECESSED"}
OPTION_GROUPS = {"FINISH", "BLADE_SPAN", "DOWNROD", "GLASS", "CONTROL"}
ACCOUNT_STATUSES = {"ACTIVE", "SUSPENDED", "CLOSED"}
GET_ALL = ("ShowroomAssociate", "StoreManager", "Designer", "FulfillmentCoordinator")


# --------------------------- TradeAccount ---------------------------
@bp.post("/trade-accounts")
@require("StoreManager")
def create_trade_account():
    body = get_body()
    business_name = req_str(body, "business_name")
    contact_email = req_str(body, "contact_email")
    credit_limit = opt_int(body, "credit_limit_cents", 0)
    rec = new_base()
    rec.update(
        {
            "business_name": business_name,
            "contact_email": contact_email,
            "credit_limit_cents": credit_limit,
            "status": "ACTIVE",
        }
    )
    insert("trade_accounts", rec)
    return created(serializers.trade_account(rec))


@bp.get("/trade-accounts/<rec_id>")
@require(*GET_ALL)
def get_trade_account(rec_id):
    rec = fetch("trade_accounts", rec_id)
    return ok(serializers.trade_account(rec))


@bp.patch("/trade-accounts/<rec_id>")
@require("StoreManager")
def patch_trade_account(rec_id):
    rec = fetch("trade_accounts", rec_id)
    body = get_body()
    changed = False
    if "credit_limit_cents" in body and body["credit_limit_cents"] is not None:
        rec["credit_limit_cents"] = req_int(body, "credit_limit_cents")
        changed = True
    if "status" in body and body["status"] is not None:
        rec["status"] = req_enum(body, "status", ACCOUNT_STATUSES)
        changed = True
    if changed:
        touch(rec)
    return ok(serializers.trade_account(rec))


# --------------------------- FixtureModel ---------------------------
def _normalize_options(body):
    raw = body.get("options")
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise err("ERR_INVALID_REQUEST", "options must be an array")
    out = []
    for item in raw:
        if not isinstance(item, dict):
            raise err("ERR_INVALID_REQUEST", "each option must be an object")
        opt_id = item.get("option_id")
        if not isinstance(opt_id, str) or opt_id == "":
            raise err("ERR_INVALID_REQUEST", "option.option_id is required")
        group = item.get("group")
        if group is not None and group not in OPTION_GROUPS:
            raise err("ERR_INVALID_REQUEST", "option.group is invalid")
        price_delta = item.get("price_delta_cents", 0)
        wattage_delta = item.get("wattage_delta", 0)
        if not isinstance(price_delta, int) or isinstance(price_delta, bool):
            raise err("ERR_INVALID_REQUEST", "option.price_delta_cents must be an integer")
        if not isinstance(wattage_delta, int) or isinstance(wattage_delta, bool):
            raise err("ERR_INVALID_REQUEST", "option.wattage_delta must be an integer")
        out.append(
            {
                "option_id": opt_id,
                "group": group,
                "label": item.get("label", ""),
                "price_delta_cents": price_delta,
                "wattage_delta": wattage_delta,
                "sku_suffix": item.get("sku_suffix", "") or "",
            }
        )
    return out


@bp.post("/fixture-models")
@require("StoreManager")
def create_fixture_model():
    body = get_body()
    sku_base = req_str(body, "sku_base")
    category = req_enum(body, "category", CATEGORIES)
    base_price = req_int(body, "base_price_cents")
    base_wattage = req_int(body, "base_wattage")
    energy_star = req_bool_default(body, "energy_star", False)
    special_order_only = req_bool_default(body, "special_order_only", False)
    supplier_lead_days = opt_int(body, "supplier_lead_days", 0)
    options = _normalize_options(body)
    rec = new_base()
    rec.update(
        {
            "sku_base": sku_base,
            "category": category,
            "base_price_cents": base_price,
            "base_wattage": base_wattage,
            "energy_star": energy_star,
            "special_order_only": special_order_only,
            "supplier_lead_days": supplier_lead_days,
            "options": options,
        }
    )
    insert("fixture_models", rec)
    return created(serializers.fixture_model(rec))


@bp.get("/fixture-models/<rec_id>")
@require(*GET_ALL)
def get_fixture_model(rec_id):
    rec = fetch("fixture_models", rec_id)
    return ok(serializers.fixture_model(rec))


# --------------------------- Installer ---------------------------
@bp.post("/installers")
@require("StoreManager")
def create_installer():
    body = get_body()
    name = req_str(body, "name")
    service_area = req_str(body, "service_area")
    daily_capacity = opt_int(body, "daily_capacity", 3)
    rec = new_base()
    rec.update(
        {
            "name": name,
            "service_area": service_area,
            "daily_capacity": daily_capacity,
            "active_referral_count": 0,
        }
    )
    insert("installers", rec)
    return created(serializers.installer(rec))


@bp.get("/installers/<rec_id>")
@require(*GET_ALL)
def get_installer(rec_id):
    rec = fetch("installers", rec_id)
    return ok(serializers.installer(rec))


# --------------------------- DeliveryTruck ---------------------------
@bp.post("/delivery-trucks")
@require("StoreManager")
def create_delivery_truck():
    body = get_body()
    name = req_str(body, "name")
    capacity_units = opt_int(body, "capacity_units", 20)
    rec = new_base()
    rec.update({"name": name, "capacity_units": capacity_units})
    insert("delivery_trucks", rec)
    return created(serializers.delivery_truck(rec))


# --------------------------- RebateProgram ---------------------------
@bp.post("/rebate-programs")
@require("StoreManager")
def create_rebate_program():
    body = get_body()
    name = req_str(body, "name")
    rebate_rate = req_number(body, "rebate_rate")
    wattage_ceiling = req_int(body, "wattage_ceiling")
    budget_total = req_int(body, "budget_total_cents")
    rec = new_base()
    rec.update(
        {
            "name": name,
            "rebate_rate": rebate_rate,
            "wattage_ceiling": wattage_ceiling,
            "budget_total_cents": budget_total,
        }
    )
    insert("rebate_programs", rec)
    return created(serializers.rebate_program(rec))


@bp.get("/rebate-programs/<rec_id>")
@require("ShowroomAssociate", "StoreManager", "FulfillmentCoordinator")
def get_rebate_program(rec_id):
    rec = fetch("rebate_programs", rec_id)
    return ok(serializers.rebate_program(rec))


# --------------------------- Logical clock ---------------------------
@bp.post("/_clock/set_current_utc")
@require("StoreManager")
def set_clock():
    body = get_body()
    to = req_datetime(body, "to_iso8601")
    db.clock = to
    return ok_empty()
