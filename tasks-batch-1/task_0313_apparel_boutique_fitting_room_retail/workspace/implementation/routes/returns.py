"""Returns, exchanges, and refund compensation (PRD §3.7)."""
from flask import Blueprint, request

import errors
from db import db, stamp_new, touch
from errors import err
from middleware import authenticate, require_role, get_json_body
from response import success, list_success
from services.common import (
    get_or_404, require_str, require_enum, parse_pagination, paginate,
    serialize, serialize_list, recompute_variant,
)
from services.pricing import reverse_points_for_line, tier_for_spend
from services.boutique_ledger import recompute_store_credit_outstanding

bp = Blueprint("returns", __name__)


@bp.post("/returns")
def create_return():
    user_id, role = authenticate()
    require_role(role, {"StoreAssociate", "Customer"})
    body = get_json_body()
    sales_order_id = require_str(body, "sales_order_id")
    order_line_id = require_str(body, "order_line_id")
    order = get_or_404("sales_order", sales_order_id)
    line = get_or_404("order_line", order_line_id)

    # Ownership: customer acting on own order (priority 4).
    if role == "Customer" and user_id != order["customer_id"]:
        raise err(errors.ERR_NOT_RESOURCE_OWNER, "not the resource owner")

    resolution = require_enum(body, "resolution", {"REFUND", "EXCHANGE"})
    exchange_sku_variant_id = body.get("exchange_sku_variant_id")
    if resolution == "EXCHANGE":
        if not exchange_sku_variant_id:
            raise err(errors.ERR_INVALID_REQUEST, "exchange_sku_variant_id required for EXCHANGE")
        get_or_404("sku_variant", exchange_sku_variant_id)

    # The order line must belong to the named order.
    if line["sales_order_id"] != sales_order_id:
        raise err(errors.ERR_NOT_FOUND, "order line does not belong to this order")

    rec = stamp_new({
        "sales_order_id": sales_order_id,
        "order_line_id": order_line_id,
        "resolution": resolution,
        "exchange_sku_variant_id": exchange_sku_variant_id,
        "status": "REQUESTED",
        "refund_cents": 0,
        "points_reversed": 0,
    })
    db.return_requests[rec["id"]] = rec
    return success(serialize(rec), 201)


@bp.get("/returns/<rid>")
def get_return(rid):
    _, role = authenticate()
    require_role(role, {"StoreManager", "StoreAssociate", "Customer"})
    rec = get_or_404("return_request", rid)
    return success(serialize(rec))


@bp.get("/sales-orders/<rid>/returns")
def list_order_returns(rid):
    _, role = authenticate()
    require_role(role, {"StoreManager", "StoreAssociate", "Customer"})
    get_or_404("sales_order", rid)
    limit, offset = parse_pagination()
    items = [r for r in db.return_requests.values() if r["sales_order_id"] == rid]
    window, total = paginate(items, limit, offset)
    return list_success(serialize_list(window), limit, offset, total)


@bp.get("/returns")
def list_returns():
    _, role = authenticate()
    require_role(role, {"StoreManager", "StoreAssociate", "Customer"})
    limit, offset = parse_pagination()
    items = list(db.return_requests.values())
    order_line_id = request.args.get("order_line_id")
    exchange_sku_variant_id = request.args.get("exchange_sku_variant_id")
    if order_line_id is not None:
        items = [r for r in items if r["order_line_id"] == order_line_id]
    if exchange_sku_variant_id is not None:
        items = [r for r in items if r["exchange_sku_variant_id"] == exchange_sku_variant_id]
    window, total = paginate(items, limit, offset)
    return list_success(serialize_list(window), limit, offset, total)


@bp.post("/returns/<rid>/approve")
def approve_return(rid):
    _, role = authenticate()
    require_role(role, {"StoreAssociate"})
    rr = get_or_404("return_request", rid)
    # State (priority 6): must be REQUESTED.
    if rr["status"] != "REQUESTED":
        raise err(errors.ERR_INVALID_STATE, "approve requires REQUESTED")
    order = db.sales_orders[rr["sales_order_id"]]
    # State before temporal (priority 8): order fulfillment COMPLETED.
    if order["fulfillment_status"] != "COMPLETED":
        raise err(errors.ERR_ORDER_NOT_RETURNABLE_STATE, "order not in returnable state")
    boutique = db.boutiques[order["boutique_id"]]
    # Temporal window (priority 9).
    anchor = order["return_anchor_date"]
    if anchor is None or (boutique["current_business_date"] - anchor) > boutique["return_window_days"]:
        raise err(errors.ERR_RETURN_WINDOW_CLOSED, "return window closed")

    line = db.order_lines[rr["order_line_id"]]
    customer = db.customers[order["customer_id"]]

    # Exchange availability (priority 17).
    if rr["resolution"] == "EXCHANGE":
        ex_variant = db.sku_variants.get(rr["exchange_sku_variant_id"])
        if ex_variant is None or ex_variant["available"] < 1:
            raise err(errors.ERR_EXCHANGE_UNAVAILABLE, "exchange variant unavailable")

    # CASCADE L1: order line status.
    line["status"] = "RETURNED" if rr["resolution"] == "REFUND" else "EXCHANGED"
    touch(line)

    # CASCADE L2/L3: restock the returned variant, bubble up.
    variant = db.sku_variants[line["sku_variant_id"]]
    variant["on_hand"] += line["qty"]
    recompute_variant(variant)

    # Resolution-specific ledger effect.
    if rr["resolution"] == "REFUND":
        rr["refund_cents"] = line["line_total_cents"]
        customer["store_credit_cents"] += line["line_total_cents"]
    else:  # EXCHANGE
        ex_variant = db.sku_variants[rr["exchange_sku_variant_id"]]
        ex_variant["reserved"] += 1
        recompute_variant(ex_variant)

    # Reverse loyalty for this line (prorated).
    points_reversed = reverse_points_for_line(
        order["points_earned"], line["line_total_cents"], order["subtotal_cents"]
    )
    rr["points_reversed"] = points_reversed
    customer["loyalty_points"] = max(0, customer["loyalty_points"] - points_reversed)
    customer["captured_spend_cents"] = max(0, customer["captured_spend_cents"] - line["line_total_cents"])
    customer["loyalty_tier"] = tier_for_spend(customer["captured_spend_cents"])

    rr["status"] = "APPROVED"
    touch(rr)
    touch(customer)

    # Full-return: if no SOLD line remains, order payment CAPTURED->REFUNDED and
    # reverse any still-outstanding points to the pre-order baseline.
    remaining_sold = any(
        l["sales_order_id"] == order["id"] and l["status"] == "SOLD"
        for l in db.order_lines.values()
    )
    if not remaining_sold and order["payment_status"] == "CAPTURED":
        already_reversed = sum(
            r["points_reversed"]
            for r in db.return_requests.values()
            if r["sales_order_id"] == order["id"] and r["status"] == "APPROVED"
        )
        residual = order["points_earned"] - already_reversed
        if residual > 0:
            customer["loyalty_points"] = max(0, customer["loyalty_points"] - residual)
            touch(customer)
        # Recompute tier after baseline restore.
        customer["loyalty_tier"] = tier_for_spend(customer["captured_spend_cents"])
        order["payment_status"] = "REFUNDED"
        touch(order)

    recompute_store_credit_outstanding(customer["boutique_id"])
    return success(serialize(rr))


@bp.post("/returns/<rid>/reject")
def reject_return(rid):
    _, role = authenticate()
    require_role(role, {"StoreManager"})
    rr = get_or_404("return_request", rid)
    if rr["status"] != "REQUESTED":
        raise err(errors.ERR_INVALID_STATE, "reject requires REQUESTED")
    rr["status"] = "REJECTED"
    touch(rr)
    return success(serialize(rr))


@bp.post("/returns/<rid>/void")
def void_return(rid):
    _, role = authenticate()
    require_role(role, {"StoreManager"})
    rr = get_or_404("return_request", rid)
    if rr["status"] != "APPROVED":
        raise err(errors.ERR_INVALID_STATE, "void requires APPROVED")
    if rr["resolution"] != "REFUND":
        raise err(errors.ERR_INVALID_STATE, "only REFUND returns are voidable")

    order = db.sales_orders[rr["sales_order_id"]]
    line = db.order_lines[rr["order_line_id"]]
    customer = db.customers[order["customer_id"]]

    # COMPENSATION: line back to SOLD; un-restock.
    line["status"] = "SOLD"
    touch(line)
    variant = db.sku_variants[line["sku_variant_id"]]
    variant["on_hand"] -= line["qty"]
    recompute_variant(variant)

    # Claw back refund store credit.
    customer["store_credit_cents"] = max(0, customer["store_credit_cents"] - rr["refund_cents"])

    # Re-mint reversed points and captured spend.
    customer["loyalty_points"] += rr["points_reversed"]
    customer["captured_spend_cents"] += line["line_total_cents"]
    customer["loyalty_tier"] = tier_for_spend(customer["captured_spend_cents"])

    rr["status"] = "VOIDED"
    touch(rr)
    touch(customer)
    recompute_store_credit_outstanding(customer["boutique_id"])
    return success(serialize(rr))
