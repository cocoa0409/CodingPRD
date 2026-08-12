"""Shipper, Customer, Commodity, DailyPrice routes."""

from flask import Blueprint, request

from db import store
from errors import (
    raise_error,
    ERR_VALIDATION,
    ERR_TERMS_EXCEEDED,
    ERR_DUPLICATE_PRICE,
    ERR_STALE_VERSION,
)
from middleware import require_roles, check_customer_ownership, ALL_ROLES
from response import success_object, success_list
from services.domain import (
    get_json_body,
    require_fields,
    req_string,
    req_int,
    req_positive_int,
    req_number,
    req_positive_number,
    req_bool,
    req_enum,
    req_date,
    is_int,
    is_bool,
    is_number,
    is_str,
    lookup,
    stamp_new,
    touch,
    paginate,
    sorted_by_created,
    mid_price,
    recompute_customer_credit_exposure,
    DATE_FMT,
    Decimal,
)

bp = Blueprint("parties", __name__)


# ---------------------------------------------------------------------------
# Shippers
# ---------------------------------------------------------------------------

@bp.post("/market/shippers")
def create_shipper():
    require_roles(["MarketAdmin"])
    body = get_json_body()
    require_fields(body, ["name", "paca_license"])
    shipper = stamp_new(
        {
            "name": req_string(body, "name"),
            "paca_license": req_string(body, "paca_license"),
            "status": "ACTIVE",
            "trust_exposure_cents": 0,
        }
    )
    store.shippers[shipper["id"]] = shipper
    return success_object(shipper, 201)


@bp.get("/market/shippers/<shipper_id>")
def get_shipper(shipper_id):
    user_id, role = require_roles(ALL_ROLES)
    shipper = lookup(store.shippers, shipper_id, "Shipper")
    return success_object(shipper, 200)


# ---------------------------------------------------------------------------
# Customers
# ---------------------------------------------------------------------------

def _validate_terms(terms_days, special_agreement):
    if terms_days > 30 and not special_agreement:
        raise_error(
            ERR_TERMS_EXCEEDED,
            "terms_days > 30 requires paca_special_agreement == true",
        )


@bp.post("/market/customers")
def create_customer():
    require_roles(["MarketAdmin"])
    body = get_json_body()
    require_fields(body, ["name", "credit_limit_cents"])
    name = req_string(body, "name")
    credit_limit_cents = req_int(body, "credit_limit_cents")
    if credit_limit_cents < 0:
        raise_error(ERR_VALIDATION, "credit_limit_cents must be >= 0")
    terms_days = body.get("terms_days", 10)
    if not is_int(terms_days) or terms_days <= 0:
        raise_error(ERR_VALIDATION, "terms_days must be a positive integer")
    paca_special_agreement = body.get("paca_special_agreement", False)
    if not is_bool(paca_special_agreement):
        raise_error(ERR_VALIDATION, "paca_special_agreement must be a boolean")
    _validate_terms(terms_days, paca_special_agreement)
    customer = stamp_new(
        {
            "name": name,
            "credit_limit_cents": credit_limit_cents,
            "terms_days": terms_days,
            "paca_special_agreement": paca_special_agreement,
            "status": "ACTIVE",
            "credit_exposure_cents": 0,
        }
    )
    store.customers[customer["id"]] = customer
    return success_object(customer, 201)


@bp.get("/market/customers/<customer_id>")
def get_customer(customer_id):
    user_id, role = require_roles(ALL_ROLES)
    customer = lookup(store.customers, customer_id, "Customer")
    check_customer_ownership(user_id, role, customer["id"])
    return success_object(customer, 200)


@bp.patch("/market/customers/<customer_id>")
def patch_customer(customer_id):
    require_roles(["MarketAdmin"])
    body = get_json_body()
    customer = lookup(store.customers, customer_id, "Customer")

    # Shape validation first (priority 3) before OCC/state checks.
    allowed = {
        "credit_limit_cents",
        "terms_days",
        "paca_special_agreement",
        "status",
        "expected_customer_version",
    }
    if "expected_customer_version" not in body or body["expected_customer_version"] is None:
        raise_error(ERR_VALIDATION, "expected_customer_version is required")
    expected = body["expected_customer_version"]
    if not is_int(expected):
        raise_error(ERR_VALIDATION, "expected_customer_version must be an integer")

    new_credit_limit = customer["credit_limit_cents"]
    new_terms = customer["terms_days"]
    new_special = customer["paca_special_agreement"]
    new_status = customer["status"]

    if "credit_limit_cents" in body and body["credit_limit_cents"] is not None:
        v = body["credit_limit_cents"]
        if not is_int(v) or v < 0:
            raise_error(ERR_VALIDATION, "credit_limit_cents must be a non-negative integer")
        new_credit_limit = v
    if "terms_days" in body and body["terms_days"] is not None:
        v = body["terms_days"]
        if not is_int(v) or v <= 0:
            raise_error(ERR_VALIDATION, "terms_days must be a positive integer")
        new_terms = v
    if "paca_special_agreement" in body and body["paca_special_agreement"] is not None:
        v = body["paca_special_agreement"]
        if not is_bool(v):
            raise_error(ERR_VALIDATION, "paca_special_agreement must be a boolean")
        new_special = v
    if "status" in body and body["status"] is not None:
        v = body["status"]
        if not is_str(v) or v not in {"ACTIVE", "SUSPENDED"}:
            raise_error(ERR_VALIDATION, "status must be ACTIVE or SUSPENDED")
        new_status = v

    # OCC (priority between shape and state; stale -> 412)
    if expected != customer["version"]:
        raise_error(
            ERR_STALE_VERSION,
            f"expected_customer_version {expected} does not match current version {customer['version']}",
        )

    # Domain constraint: terms cap (priority 9)
    _validate_terms(new_terms, new_special)

    customer["credit_limit_cents"] = new_credit_limit
    customer["terms_days"] = new_terms
    customer["paca_special_agreement"] = new_special
    customer["status"] = new_status
    touch(customer)
    recompute_customer_credit_exposure(customer["id"])
    return success_object(customer, 200)


@bp.get("/market/customers/<customer_id>/sales-orders")
def list_customer_orders(customer_id):
    user_id, role = require_roles(ALL_ROLES)
    customer = lookup(store.customers, customer_id, "Customer")
    check_customer_ownership(user_id, role, customer["id"])
    items = [
        o for o in store.sales_orders.values() if o["customer_id"] == customer_id
    ]
    items = sorted_by_created(items)
    page, pagination = paginate(items)
    return success_list(page, pagination, 200)


@bp.get("/market/customers/<customer_id>/invoices")
def list_customer_invoices(customer_id):
    user_id, role = require_roles(ALL_ROLES)
    customer = lookup(store.customers, customer_id, "Customer")
    check_customer_ownership(user_id, role, customer["id"])
    items = [i for i in store.invoices.values() if i["customer_id"] == customer_id]
    items = sorted_by_created(items)
    page, pagination = paginate(items)
    return success_list(page, pagination, 200)


# ---------------------------------------------------------------------------
# Commodities
# ---------------------------------------------------------------------------

@bp.post("/market/commodities")
def create_commodity():
    require_roles(["MarketAdmin"])
    body = get_json_body()
    require_fields(body, ["code", "name", "ethylene_class", "temp_min_f", "temp_max_f"])
    code = req_string(body, "code")
    name = req_string(body, "name")
    ethylene_class = req_enum(body, "ethylene_class", {"PRODUCER", "SENSITIVE", "NEUTRAL"})
    temp_min_f = req_number(body, "temp_min_f")
    temp_max_f = req_number(body, "temp_max_f")
    if temp_max_f < temp_min_f:
        raise_error(ERR_VALIDATION, "temp_max_f must be >= temp_min_f")
    max_violation_minutes = body.get("max_violation_minutes", 60)
    if not is_int(max_violation_minutes) or max_violation_minutes < 0:
        raise_error(ERR_VALIDATION, "max_violation_minutes must be a non-negative integer")
    commodity = stamp_new(
        {
            "code": code,
            "name": name,
            "ethylene_class": ethylene_class,
            "temp_min_f": float(temp_min_f),
            "temp_max_f": float(temp_max_f),
            "max_violation_minutes": max_violation_minutes,
        }
    )
    store.commodities[commodity["id"]] = commodity
    return success_object(commodity, 201)


@bp.get("/market/commodities/<commodity_id>")
def get_commodity(commodity_id):
    require_roles(ALL_ROLES)
    commodity = lookup(store.commodities, commodity_id, "Commodity")
    return success_object(commodity, 200)


# ---------------------------------------------------------------------------
# Daily prices
# ---------------------------------------------------------------------------

@bp.post("/market/daily-prices")
def create_daily_price():
    require_roles(["MarketAdmin"])
    body = get_json_body()
    require_fields(body, ["commodity_id", "market_date", "low_price", "high_price"])
    commodity_id = body.get("commodity_id")
    if not is_str(commodity_id):
        raise_error(ERR_VALIDATION, "commodity_id must be a string")
    market_date = req_date(body, "market_date")
    low_price = req_positive_number(body, "low_price")
    high_price = req_positive_number(body, "high_price")
    if high_price < low_price:
        raise_error(ERR_VALIDATION, "high_price must be >= low_price")
    # existence of commodity FK (priority 4)
    lookup(store.commodities, commodity_id, "Commodity")
    # uniqueness per (commodity_id, market_date)
    market_date_str = market_date.strftime(DATE_FMT)
    for dp in store.daily_prices.values():
        if dp["commodity_id"] == commodity_id and dp["market_date"] == market_date_str:
            raise_error(
                ERR_DUPLICATE_PRICE,
                f"DailyPrice already exists for ({commodity_id}, {market_date_str})",
            )
    price = stamp_new(
        {
            "commodity_id": commodity_id,
            "market_date": market_date_str,
            "low_price": float(low_price),
            "high_price": float(high_price),
            "mid_price": mid_price(low_price, high_price),
        }
    )
    store.daily_prices[price["id"]] = price
    return success_object(price, 201)


@bp.get("/market/daily-prices/<price_id>")
def get_daily_price(price_id):
    require_roles(ALL_ROLES)
    price = lookup(store.daily_prices, price_id, "DailyPrice")
    return success_object(price, 200)


@bp.get("/market/daily-prices")
def list_daily_prices():
    require_roles(ALL_ROLES)
    commodity_id = request.args.get("commodity_id")
    market_date = request.args.get("market_date")
    items = list(store.daily_prices.values())
    if commodity_id is not None:
        items = [p for p in items if p["commodity_id"] == commodity_id]
    if market_date is not None:
        items = [p for p in items if p["market_date"] == market_date]
    items = sorted_by_created(items)
    page, pagination = paginate(items)
    return success_list(page, pagination, 200)
