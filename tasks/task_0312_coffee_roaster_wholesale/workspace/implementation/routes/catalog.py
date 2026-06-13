"""Catalog config: price tiers, roast profiles, products, accounts, clock."""
from datetime import timedelta

from flask import Blueprint, request

import errors
from db import store
from middleware import get_identity, require_role
from helpers import (
    get_body, require_fields, as_int, as_str, parse_pagination, paginate,
    sort_by_created, new_record, touch,
)
from response import object_response, array_response
from services import lookups, serializers
from services.inventory import recompute_account_balance
from services.clock import parse_iso8601

bp = Blueprint("catalog", __name__)


# ==========================================================================
# Price tiers
# ==========================================================================
@bp.post("/price-tiers")
def create_tier():
    _, role = get_identity()
    require_role(role, {"SalesRep"})
    body = get_body()
    require_fields(body, ["code", "discount_bps", "min_monthly_kg", "freshness_max_days"])
    code = as_str(body["code"], "code")
    discount_bps = as_int(body["discount_bps"], "discount_bps")
    min_monthly_kg = as_int(body["min_monthly_kg"], "min_monthly_kg")
    freshness_max_days = as_int(body["freshness_max_days"], "freshness_max_days")
    if not (0 <= discount_bps <= 3000):
        raise errors.invalid_request("discount_bps must be between 0 and 3000")

    # uniqueness among non-archived (priority 5)
    for t in store.price_tiers.values():
        if not t["archived"] and t["code"] == code:
            raise errors.duplicate("price tier code already in use")

    rec = new_record()
    rec.update({
        "code": code,
        "discount_bps": discount_bps,
        "min_monthly_kg": min_monthly_kg,
        "freshness_max_days": freshness_max_days,
        "archived": False,
    })
    store.price_tiers[rec["id"]] = rec
    return object_response(serializers.tier_public(rec), 201)


@bp.get("/price-tiers")
def list_tiers():
    _, role = get_identity()
    require_role(role, {"SalesRep", "RoasterStaff"})
    limit, offset = parse_pagination()
    include_archived = request.args.get("archived", "").lower() == "true"
    items = [t for t in store.price_tiers.values() if include_archived or not t["archived"]]
    items = sort_by_created(items)
    page, total = paginate(items, limit, offset)
    return array_response([serializers.tier_public(t) for t in page], limit, offset, total)


@bp.get("/price-tiers/<tid>")
def get_tier(tid):
    _, role = get_identity()
    require_role(role, {"SalesRep", "RoasterStaff"})
    rec = lookups.get_tier(tid)
    return object_response(serializers.tier_public(rec))


# ==========================================================================
# Roast profiles
# ==========================================================================
@bp.post("/roast-profiles")
def create_profile():
    _, role = get_identity()
    require_role(role, {"RoasterStaff"})
    body = get_body()
    require_fields(body, ["name", "roast_level", "expected_shrink_bps", "charge_temp_c"])
    name = as_str(body["name"], "name")
    roast_level = body["roast_level"]
    if roast_level not in ("LIGHT", "MEDIUM", "DARK"):
        raise errors.invalid_request("roast_level must be LIGHT, MEDIUM or DARK")
    expected_shrink_bps = as_int(body["expected_shrink_bps"], "expected_shrink_bps")
    charge_temp_c = as_int(body["charge_temp_c"], "charge_temp_c")
    if not (500 <= expected_shrink_bps <= 2500):
        raise errors.invalid_request("expected_shrink_bps must be between 500 and 2500")

    rec = new_record()
    rec.update({
        "name": name,
        "roast_level": roast_level,
        "expected_shrink_bps": expected_shrink_bps,
        "charge_temp_c": charge_temp_c,
    })
    store.roast_profiles[rec["id"]] = rec
    return object_response(serializers.roast_profile_public(rec), 201)


@bp.get("/roast-profiles")
def list_profiles():
    _, role = get_identity()
    require_role(role, {"RoasterStaff", "SalesRep"})
    limit, offset = parse_pagination()
    roast_level = request.args.get("roast_level")
    items = list(store.roast_profiles.values())
    if roast_level is not None:
        items = [p for p in items if p["roast_level"] == roast_level]
    items = sort_by_created(items)
    page, total = paginate(items, limit, offset)
    return array_response([serializers.roast_profile_public(p) for p in page], limit, offset, total)


@bp.get("/roast-profiles/<pid>")
def get_profile(pid):
    _, role = get_identity()
    require_role(role, {"RoasterStaff", "SalesRep"})
    rec = lookups.get_profile(pid)
    return object_response(serializers.roast_profile_public(rec))


# ==========================================================================
# Products
# ==========================================================================
@bp.post("/products")
def create_product():
    _, role = get_identity()
    require_role(role, {"SalesRep", "RoasterStaff"})
    body = get_body()
    require_fields(body, ["sku", "name", "roast_profile_id", "base_price_cents_per_kg", "freshness_window_days"])
    sku = as_str(body["sku"], "sku")
    name = as_str(body["name"], "name")
    base_price = as_int(body["base_price_cents_per_kg"], "base_price_cents_per_kg")
    freshness_window_days = as_int(body["freshness_window_days"], "freshness_window_days")
    # existence of FK target (priority 3)
    lookups.get_profile(as_str(body["roast_profile_id"], "roast_profile_id"))

    # uniqueness among non-archived (priority 5)
    for p in store.products.values():
        if not p["archived"] and p["sku"] == sku:
            raise errors.duplicate("product sku already in use")

    rec = new_record()
    rec.update({
        "sku": sku,
        "name": name,
        "roast_profile_id": body["roast_profile_id"],
        "base_price_cents_per_kg": base_price,
        "freshness_window_days": freshness_window_days,
        "archived": False,
    })
    store.products[rec["id"]] = rec
    return object_response(serializers.product_public(rec), 201)


@bp.get("/products")
def list_products():
    _, role = get_identity()
    require_role(role, {"SalesRep", "RoasterStaff", "WholesaleBuyer"})
    limit, offset = parse_pagination()
    include_archived = request.args.get("archived", "").lower() == "true"
    roast_profile_id = request.args.get("roast_profile_id")
    items = [p for p in store.products.values() if include_archived or not p["archived"]]
    if roast_profile_id is not None:
        items = [p for p in items if p["roast_profile_id"] == roast_profile_id]
    items = sort_by_created(items)
    page, total = paginate(items, limit, offset)
    return array_response([serializers.product_public(p) for p in page], limit, offset, total)


@bp.get("/products/<pid>")
def get_product(pid):
    _, role = get_identity()
    require_role(role, {"SalesRep", "RoasterStaff", "WholesaleBuyer"})
    rec = lookups.get_product(pid)
    return object_response(serializers.product_public(rec))


@bp.post("/products/<pid>/archive")
def archive_product(pid):
    _, role = get_identity()
    require_role(role, {"SalesRep", "RoasterStaff"})
    rec = lookups.get_product(pid)
    rec["archived"] = True
    touch(rec)
    return object_response(serializers.product_public(rec), 200)


# ==========================================================================
# Wholesale accounts
# ==========================================================================
@bp.post("/accounts")
def create_account():
    _, role = get_identity()
    require_role(role, {"SalesRep"})
    body = get_body()
    require_fields(body, ["name", "price_tier_id", "net_terms_days", "credit_limit_cents"])
    name = as_str(body["name"], "name")
    net_terms_days = as_int(body["net_terms_days"], "net_terms_days")
    credit_limit = as_int(body["credit_limit_cents"], "credit_limit_cents")
    if net_terms_days not in (0, 15, 30, 45, 60):
        raise errors.invalid_request("net_terms_days must be one of 0, 15, 30, 45, 60")
    # FK existence (priority 3)
    lookups.get_tier(as_str(body["price_tier_id"], "price_tier_id"))

    rec = new_record()
    rec.update({
        "name": name,
        "price_tier_id": body["price_tier_id"],
        "net_terms_days": net_terms_days,
        "credit_limit_cents": credit_limit,
        "outstanding_balance_cents": 0,
        "status": "ACTIVE",
    })
    store.accounts[rec["id"]] = rec
    return object_response(serializers.account_public(rec), 201)


@bp.get("/accounts")
def list_accounts():
    _, role = get_identity()
    require_role(role, {"SalesRep", "RoasterStaff"})
    limit, offset = parse_pagination()
    price_tier_id = request.args.get("price_tier_id")
    status = request.args.get("status")
    items = list(store.accounts.values())
    if price_tier_id is not None:
        items = [a for a in items if a["price_tier_id"] == price_tier_id]
    if status is not None:
        items = [a for a in items if a["status"] == status]
    items = sort_by_created(items)
    page, total = paginate(items, limit, offset)
    out = []
    for a in page:
        recompute_account_balance(a)
        out.append(serializers.account_public(a))
    return array_response(out, limit, offset, total)


@bp.get("/accounts/<aid>")
def get_account(aid):
    user_id, role = get_identity()
    require_role(role, {"SalesRep", "RoasterStaff", "WholesaleBuyer"})
    # buyer ownership (auth, priority 2) before existence (priority 3)
    lookups.assert_buyer_owns_account(role, user_id, aid)
    rec = lookups.get_account(aid)
    recompute_account_balance(rec)
    return object_response(serializers.account_public(rec))


# ==========================================================================
# Test-driving clock
# ==========================================================================
@bp.post("/_clock/set")
def clock_set():
    _, role = get_identity()
    require_role(role, {"SalesRep", "RoasterStaff"})
    body = get_body()
    require_fields(body, ["to_iso8601"])
    store.set_clock(parse_iso8601(body["to_iso8601"]))
    return object_response({}, 200)


@bp.post("/_clock/advance")
def clock_advance():
    _, role = get_identity()
    require_role(role, {"SalesRep", "RoasterStaff"})
    body = get_body()
    require_fields(body, ["to_iso8601"])
    store.set_clock(parse_iso8601(body["to_iso8601"]))
    from services.aging import run_aging_sweep
    run_aging_sweep()
    return object_response({}, 200)
