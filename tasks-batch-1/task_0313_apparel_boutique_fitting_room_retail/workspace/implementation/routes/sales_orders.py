"""Sales orders + order lines: parallel payment/fulfillment axes, order pricing,
capture, and loyalty accrual (PRD §3.6)."""
from flask import Blueprint, request

import errors
from db import db, stamp_new, touch
from errors import err
from middleware import authenticate, require_role, get_json_body
from response import success, list_success
from services.common import (
    get_or_404, require_str, require_int, parse_pagination, paginate,
    serialize, serialize_list, recompute_variant,
)
from services.pricing import (
    price_order, mint_points, tier_for_spend,
)

bp = Blueprint("sales_orders", __name__)


def _order_lines(order_id):
    return [l for l in db.order_lines.values() if l["sales_order_id"] == order_id]


# --- Sales orders ---

@bp.post("/sales-orders")
def create_order():
    _, role = authenticate()
    require_role(role, {"StoreAssociate"})
    body = get_json_body()
    customer_id = require_str(body, "customer_id")
    customer = get_or_404("customer", customer_id)
    rec = stamp_new({
        "customer_id": customer_id,
        "boutique_id": customer["boutique_id"],
        "payment_status": "UNPAID",
        "fulfillment_status": "OPEN",
        "subtotal_cents": 0,
        "loyalty_discount_cents": 0,
        "tax_cents": 0,
        "store_credit_applied_cents": 0,
        "total_cents": 0,
        "points_earned": 0,
        "return_anchor_date": None,
    })
    db.sales_orders[rec["id"]] = rec
    return success(serialize(rec), 201)


@bp.get("/sales-orders/<rid>")
def get_order(rid):
    user_id, role = authenticate()
    require_role(role, {"StoreManager", "StoreAssociate", "Customer"})
    rec = get_or_404("sales_order", rid)
    if role == "Customer" and user_id != rec["customer_id"]:
        raise err(errors.ERR_NOT_RESOURCE_OWNER, "not the resource owner")
    return success(serialize(rec))


@bp.get("/sales-orders")
def list_orders():
    _, role = authenticate()
    require_role(role, {"StoreManager", "StoreAssociate", "Customer"})
    limit, offset = parse_pagination()
    items = list(db.sales_orders.values())
    customer_id = request.args.get("customer_id")
    boutique_id = request.args.get("boutique_id")
    if customer_id is not None:
        items = [o for o in items if o["customer_id"] == customer_id]
    if boutique_id is not None:
        items = [o for o in items if o["boutique_id"] == boutique_id]
    window, total = paginate(items, limit, offset)
    return list_success(serialize_list(window), limit, offset, total)


# --- Order lines ---

@bp.post("/sales-orders/<rid>/lines")
def add_line(rid):
    _, role = authenticate()
    require_role(role, {"StoreAssociate"})
    order = get_or_404("sales_order", rid)
    body = get_json_body()
    sku_variant_id = require_str(body, "sku_variant_id")
    variant = get_or_404("sku_variant", sku_variant_id)
    qty = require_int(body, "qty")
    if qty < 1:
        raise err(errors.ERR_INVALID_REQUEST, "qty must be >= 1")
    style = db.styles[variant["style_id"]]
    unit_price = style["current_price_cents"]
    rec = stamp_new({
        "sales_order_id": order["id"],
        "sku_variant_id": sku_variant_id,
        "qty": qty,
        "unit_price_cents": unit_price,
        "line_total_cents": unit_price * qty,
        "status": "SOLD",
    })
    db.order_lines[rec["id"]] = rec
    return success(serialize(rec), 201)


@bp.get("/sales-orders/<rid>/lines")
def list_order_lines(rid):
    _, role = authenticate()
    require_role(role, {"StoreManager", "StoreAssociate", "Customer"})
    get_or_404("sales_order", rid)
    limit, offset = parse_pagination()
    items = _order_lines(rid)
    window, total = paginate(items, limit, offset)
    return list_success(serialize_list(window), limit, offset, total)


@bp.get("/order-lines/<rid>")
def get_line(rid):
    _, role = authenticate()
    require_role(role, {"StoreManager", "StoreAssociate", "Customer"})
    rec = get_or_404("order_line", rid)
    return success(serialize(rec))


@bp.get("/order-lines")
def list_lines():
    _, role = authenticate()
    require_role(role, {"StoreManager", "StoreAssociate", "Customer"})
    limit, offset = parse_pagination()
    items = list(db.order_lines.values())
    sku_variant_id = request.args.get("sku_variant_id")
    if sku_variant_id is not None:
        items = [l for l in items if l["sku_variant_id"] == sku_variant_id]
    window, total = paginate(items, limit, offset)
    return list_success(serialize_list(window), limit, offset, total)


# --- Payment axis transitions ---

@bp.post("/sales-orders/<rid>/authorize")
def authorize_order(rid):
    _, role = authenticate()
    require_role(role, {"StoreAssociate"})
    order = get_or_404("sales_order", rid)
    # State (priority 6): authorize defined only from UNPAID.
    if order["payment_status"] != "UNPAID":
        raise err(errors.ERR_INVALID_STATE, "authorize requires UNPAID")
    # Preconditions.
    if order["fulfillment_status"] != "OPEN":
        raise err(errors.ERR_INVALID_STATE, "fulfillment must be OPEN")
    lines = _order_lines(order["id"])
    if len(lines) < 1:
        raise err(errors.ERR_INVALID_STATE, "order has no order lines")
    customer = db.customers[order["customer_id"]]
    if customer["status"] != "ACTIVE":
        raise err(errors.ERR_INVALID_STATE, "customer is not ACTIVE")

    boutique = db.boutiques[order["boutique_id"]]
    subtotal, loyalty_discount, tax = price_order(
        lines, customer["loyalty_tier"], boutique["tax_rate_bps"]
    )
    order["subtotal_cents"] = subtotal
    order["loyalty_discount_cents"] = loyalty_discount
    order["tax_cents"] = tax
    # total reflects priced (pre-store-credit) value until capture finalizes it.
    order["total_cents"] = subtotal - loyalty_discount + tax
    order["payment_status"] = "AUTHORIZED"
    touch(order)
    return success(serialize(order))


@bp.post("/sales-orders/<rid>/capture")
def capture_order(rid):
    _, role = authenticate()
    require_role(role, {"StoreAssociate"})
    order = get_or_404("sales_order", rid)
    body = get_json_body()
    redeem_store_credit = require_int(body, "redeem_store_credit", required=False, default=0)
    if redeem_store_credit is not None and redeem_store_credit < 0:
        raise err(errors.ERR_INVALID_REQUEST, "redeem_store_credit must be >= 0")

    # State (priority 6): capture defined only from AUTHORIZED.
    if order["payment_status"] != "AUTHORIZED":
        raise err(errors.ERR_INVALID_STATE, "capture requires AUTHORIZED")

    lines = _order_lines(order["id"])
    customer = db.customers[order["customer_id"]]

    # Business check 1: inventory re-check (priority 13) BEFORE store credit.
    for line in lines:
        variant = db.sku_variants[line["sku_variant_id"]]
        if variant["available"] < line["qty"]:
            raise err(errors.ERR_INSUFFICIENT_INVENTORY, "insufficient inventory at capture")

    # Business check 2: store-credit redemption ceiling (priority 14).
    redeem = redeem_store_credit or 0
    if redeem > customer["store_credit_cents"]:
        raise err(errors.ERR_INSUFFICIENT_STORE_CREDIT, "redeem exceeds store credit")

    subtotal = order["subtotal_cents"]
    loyalty_discount = order["loyalty_discount_cents"]
    tax = order["tax_cents"]
    pre_credit = subtotal - loyalty_discount + tax
    store_credit_applied = min(redeem, pre_credit)
    total = pre_credit - store_credit_applied

    order["store_credit_applied_cents"] = store_credit_applied
    order["total_cents"] = total

    # Decrement store credit wallet.
    customer["store_credit_cents"] -= store_credit_applied

    # Move inventory: decrement on_hand per line; recompute available; bubble up.
    for line in lines:
        variant = db.sku_variants[line["sku_variant_id"]]
        variant["on_hand"] -= line["qty"]
        recompute_variant(variant)

    # Mint loyalty on net cash (total).
    points_earned = mint_points(total)
    order["points_earned"] = points_earned
    customer["loyalty_points"] += points_earned
    customer["captured_spend_cents"] += total
    customer["loyalty_tier"] = tier_for_spend(customer["captured_spend_cents"])

    order["payment_status"] = "CAPTURED"
    touch(order)
    touch(customer)

    from services.boutique_ledger import recompute_store_credit_outstanding
    recompute_store_credit_outstanding(customer["boutique_id"])
    return success(serialize(order))


# --- Fulfillment axis transitions ---

@bp.post("/sales-orders/<rid>/complete")
def complete_order(rid):
    _, role = authenticate()
    require_role(role, {"StoreAssociate"})
    order = get_or_404("sales_order", rid)
    # Fulfillment OPEN->COMPLETED, precondition payment CAPTURED.
    if order["fulfillment_status"] != "OPEN":
        raise err(errors.ERR_INVALID_STATE, "complete requires fulfillment OPEN")
    if order["payment_status"] != "CAPTURED":
        raise err(errors.ERR_INVALID_STATE, "complete requires payment CAPTURED")
    boutique = db.boutiques[order["boutique_id"]]
    order["fulfillment_status"] = "COMPLETED"
    order["return_anchor_date"] = boutique["current_business_date"]
    touch(order)
    return success(serialize(order))


@bp.post("/sales-orders/<rid>/cancel")
def cancel_order(rid):
    _, role = authenticate()
    require_role(role, {"StoreAssociate"})
    order = get_or_404("sales_order", rid)
    # Fulfillment OPEN->CANCELLED; forbidden once payment CAPTURED.
    if order["fulfillment_status"] != "OPEN":
        raise err(errors.ERR_INVALID_STATE, "cancel requires fulfillment OPEN")
    if order["payment_status"] not in ("UNPAID", "AUTHORIZED"):
        raise err(errors.ERR_INVALID_STATE, "cancel forbidden once CAPTURED")
    order["fulfillment_status"] = "CANCELLED"
    touch(order)
    return success(serialize(order))
