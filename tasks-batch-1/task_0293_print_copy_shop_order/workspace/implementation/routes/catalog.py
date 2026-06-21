"""Catalog & config routes: shops, products, pricing tiers, finishing options,
presses (PRD §3.1, §3.5)."""

from flask import Blueprint

import db
import errors
from errors import err
from middleware import require_roles
from response import object_response, array_response
from services import serialize
from services.common import (
    get_body, require_fields, require_int, require_str, require_enum,
    lookup, list_collection,
)
from services import pricing

bp = Blueprint("catalog", __name__)


# ---------------------------------------------------------------------------
# Shops (PRD §3.1).
# ---------------------------------------------------------------------------
@bp.post("/shops")
@require_roles("ShopStaff")
def create_shop():
    body = get_body()
    require_fields(body, "name", "tax_rate_bps", "rush_surcharge_bps",
                   "rush_cutoff_hour_utc", "standard_turnaround_days",
                   "rush_turnaround_days", "daily_unit_capacity")
    name = require_str(body, "name")
    tax_rate_bps = require_int(body, "tax_rate_bps", min_value=0, max_value=2000)
    rush_surcharge_bps = require_int(body, "rush_surcharge_bps", min_value=0, max_value=10000)
    rush_cutoff_hour_utc = require_int(body, "rush_cutoff_hour_utc", min_value=0, max_value=23)
    standard_turnaround_days = require_int(body, "standard_turnaround_days", min_value=1)
    rush_turnaround_days = require_int(body, "rush_turnaround_days", min_value=0)
    # rush_turnaround_days must be strictly fewer than standard_turnaround_days.
    if rush_turnaround_days >= standard_turnaround_days:
        raise err(errors.ERR_VALIDATION,
                  "rush_turnaround_days must be < standard_turnaround_days")
    daily_unit_capacity = require_int(body, "daily_unit_capacity", min_value=1)

    rec = {
        "name": name,
        "tax_rate_bps": tax_rate_bps,
        "rush_surcharge_bps": rush_surcharge_bps,
        "rush_cutoff_hour_utc": rush_cutoff_hour_utc,
        "standard_turnaround_days": standard_turnaround_days,
        "rush_turnaround_days": rush_turnaround_days,
        "daily_unit_capacity": daily_unit_capacity,
    }
    db.stamp_new(rec)
    db.shops[rec["id"]] = rec
    return object_response(serialize.shop(rec), 201)


@bp.get("/shops/<shop_id>")
@require_roles("ShopStaff", "ProductionOperator", "Customer")
def read_shop(shop_id):
    rec = lookup(db.shops, shop_id)
    return object_response(serialize.shop(rec), 200)


# ---------------------------------------------------------------------------
# Products (PRD §3.1).
# ---------------------------------------------------------------------------
@bp.post("/products")
@require_roles("ShopStaff")
def create_product():
    body = get_body()
    require_fields(body, "shop_id", "name", "category", "base_unit_price_cents")
    shop_id = require_str(body, "shop_id")
    lookup(db.shops, shop_id)
    name = require_str(body, "name")
    category = require_enum(body, "category", {"COPIES", "BANNER", "BINDING"})
    base_unit_price_cents = require_int(body, "base_unit_price_cents", min_value=0)

    unit_size = 1
    if body.get("unit_size") is not None:
        unit_size = require_int(body, "unit_size", min_value=1)
    requires_proof = _opt_bool(body, "requires_proof", False)
    requires_press = _opt_bool(body, "requires_press", False)
    active = _opt_bool(body, "active", True)

    rec = {
        "shop_id": shop_id,
        "name": name,
        "category": category,
        "base_unit_price_cents": base_unit_price_cents,
        "unit_size": unit_size,
        "requires_proof": requires_proof,
        "requires_press": requires_press,
        "active": active,
    }
    db.stamp_new(rec)
    db.products[rec["id"]] = rec
    return object_response(serialize.product(rec), 201)


@bp.get("/products")
@require_roles("ShopStaff", "ProductionOperator", "Customer")
def list_products():
    from flask import request
    shop_id = request.args.get("shop_id")
    category = request.args.get("category")

    def pred(r):
        if shop_id is not None and r["shop_id"] != shop_id:
            return False
        if category is not None and r["category"] != category:
            return False
        return True

    items, limit, offset, total = list_collection(db.products, pred)
    return array_response([serialize.product(r) for r in items], limit, offset, total)


@bp.get("/products/<product_id>")
@require_roles("ShopStaff", "ProductionOperator", "Customer")
def read_product(product_id):
    rec = lookup(db.products, product_id)
    return object_response(serialize.product(rec), 200)


@bp.patch("/products/<product_id>")
@require_roles("ShopStaff")
def edit_product(product_id):
    rec = lookup(db.products, product_id)
    body = get_body()
    changed = False
    if "base_unit_price_cents" in body and body["base_unit_price_cents"] is not None:
        rec["base_unit_price_cents"] = require_int(body, "base_unit_price_cents", min_value=0)
        changed = True
    if "name" in body and body["name"] is not None:
        rec["name"] = require_str(body, "name")
        changed = True
    if "active" in body and body["active"] is not None:
        rec["active"] = _opt_bool(body, "active", rec["active"])
        changed = True
    if changed:
        db.touch(rec)
        # Side effect: recompute estimate_line_cents on every still-OPEN line
        # referencing this product (never disturbs a frozen final_line_cents).
        _recompute_open_lines_for_product(product_id)
    return object_response(serialize.product(rec), 200)


def _recompute_open_lines_for_product(product_id):
    product = db.products[product_id]
    for line in db.order_lines.values():
        if line["product_id"] == product_id and line["status"] == "OPEN":
            new_estimate = pricing.compute_line_price(
                product, line["quantity"], line["finishing_codes"])
            new_units = pricing.production_units(product, line["quantity"])
            if (new_estimate != line["estimate_line_cents"]
                    or new_units != line["production_units"]):
                line["estimate_line_cents"] = new_estimate
                line["production_units"] = new_units
                db.touch(line)


# ---------------------------------------------------------------------------
# Pricing tiers (PRD §3.1).
# ---------------------------------------------------------------------------
@bp.post("/pricing-tiers")
@require_roles("ShopStaff")
def create_pricing_tier():
    body = get_body()
    require_fields(body, "product_id", "min_quantity", "discount_bps")
    product_id = require_str(body, "product_id")
    lookup(db.products, product_id)
    min_quantity = require_int(body, "min_quantity", min_value=1)
    discount_bps = require_int(body, "discount_bps", min_value=0, max_value=10000)

    rec = {"product_id": product_id, "min_quantity": min_quantity,
           "discount_bps": discount_bps}
    db.stamp_new(rec)
    db.pricing_tiers[rec["id"]] = rec
    return object_response(serialize.pricing_tier(rec), 201)


@bp.get("/pricing-tiers")
@require_roles("ShopStaff", "ProductionOperator", "Customer")
def list_pricing_tiers():
    from flask import request
    product_id = request.args.get("product_id")
    items, limit, offset, total = list_collection(
        db.pricing_tiers,
        (lambda r: r["product_id"] == product_id) if product_id else None)
    return array_response([serialize.pricing_tier(r) for r in items], limit, offset, total)


@bp.get("/pricing-tiers/<pricing_tier_id>")
@require_roles("ShopStaff", "ProductionOperator", "Customer")
def read_pricing_tier(pricing_tier_id):
    rec = lookup(db.pricing_tiers, pricing_tier_id)
    return object_response(serialize.pricing_tier(rec), 200)


# ---------------------------------------------------------------------------
# Finishing options (PRD §3.1).
# ---------------------------------------------------------------------------
@bp.post("/finishing-options")
@require_roles("ShopStaff")
def create_finishing_option():
    body = get_body()
    require_fields(body, "product_id", "code", "surcharge_kind", "surcharge_cents")
    product_id = require_str(body, "product_id")
    lookup(db.products, product_id)
    code = require_str(body, "code")
    surcharge_kind = require_enum(body, "surcharge_kind", {"PER_UNIT", "FLAT"})
    surcharge_cents = require_int(body, "surcharge_cents", min_value=0)

    rec = {"product_id": product_id, "code": code,
           "surcharge_kind": surcharge_kind, "surcharge_cents": surcharge_cents}
    db.stamp_new(rec)
    db.finishing_options[rec["id"]] = rec
    return object_response(serialize.finishing_option(rec), 201)


@bp.get("/finishing-options")
@require_roles("ShopStaff", "ProductionOperator", "Customer")
def list_finishing_options():
    from flask import request
    product_id = request.args.get("product_id")
    items, limit, offset, total = list_collection(
        db.finishing_options,
        (lambda r: r["product_id"] == product_id) if product_id else None)
    return array_response([serialize.finishing_option(r) for r in items], limit, offset, total)


@bp.get("/finishing-options/<finishing_option_id>")
@require_roles("ShopStaff", "ProductionOperator", "Customer")
def read_finishing_option(finishing_option_id):
    rec = lookup(db.finishing_options, finishing_option_id)
    return object_response(serialize.finishing_option(rec), 200)


# ---------------------------------------------------------------------------
# Presses (PRD §3.5).
# ---------------------------------------------------------------------------
@bp.post("/presses")
@require_roles("ShopStaff")
def create_press():
    body = get_body()
    require_fields(body, "shop_id", "name")
    shop_id = require_str(body, "shop_id")
    lookup(db.shops, shop_id)
    name = require_str(body, "name")
    cleanup_buffer_minutes = 0
    if body.get("cleanup_buffer_minutes") is not None:
        cleanup_buffer_minutes = require_int(body, "cleanup_buffer_minutes", min_value=0)

    rec = {"shop_id": shop_id, "name": name,
           "cleanup_buffer_minutes": cleanup_buffer_minutes}
    db.stamp_new(rec)
    db.presses[rec["id"]] = rec
    return object_response(serialize.press(rec), 201)


@bp.get("/presses")
@require_roles("ShopStaff", "ProductionOperator", "Customer")
def list_presses():
    from flask import request
    shop_id = request.args.get("shop_id")
    items, limit, offset, total = list_collection(
        db.presses, (lambda r: r["shop_id"] == shop_id) if shop_id else None)
    return array_response([serialize.press(r) for r in items], limit, offset, total)


@bp.get("/presses/<press_id>")
@require_roles("ShopStaff", "ProductionOperator", "Customer")
def read_press(press_id):
    rec = lookup(db.presses, press_id)
    return object_response(serialize.press(rec), 200)


# ---------------------------------------------------------------------------
def _opt_bool(body, name, default):
    if name not in body or body[name] is None:
        return default
    val = body[name]
    if not isinstance(val, bool):
        raise err(errors.ERR_VALIDATION, "Field %s must be a boolean" % name)
    return val
