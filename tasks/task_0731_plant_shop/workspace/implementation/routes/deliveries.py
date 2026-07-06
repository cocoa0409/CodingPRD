"""Delivery routes: list, read, deliver."""
from flask import Blueprint, request
from clock import iso_now
from db import DB
from errors import not_found, invalid_state, unauthorized
from middleware import (
    auth_context, require_role, require_json,
    parse_pagination, sort_by_created, paginate,
)
from response import ok, ok_list
from services.common import bump
from services.loyalty import compute_accrual_points, append_ledger

bp = Blueprint("deliveries", __name__)


@bp.post("/deliveries/<did>/deliver")
def deliver(did):
    role, user_id = auth_context()
    require_role(role, {"DeliveryDriver"})
    delivery = DB.deliveries.get(did)
    if not delivery:
        raise not_found("DeliveryAssignment")
    if user_id != delivery["driver_id"]:
        raise unauthorized("not assigned driver")
    order = DB.orders.get(delivery["order_id"])
    if not order:
        raise not_found("Order")
    if delivery["status"] != "SCHEDULED":
        raise invalid_state("delivery not SCHEDULED")
    if order["payment_status"] != "PAID":
        raise invalid_state("order not PAID")

    # Cascade.
    delivery["status"] = "DELIVERED"
    bump(delivery)

    # Pre-cascade tier snapshot for final accrual.
    # PRD §3.4: "the customer's tier AS OBSERVED at the pre-cascade snapshot of
    # delivery (so a tier flip that would be caused by this very order's own
    # accrual does not apply to this order's own accrual)". This order's own
    # provisional already sits inside customer.lifetime_points_earned, so
    # subtract it back off to recover the tier state that predates this order.
    customer = DB.customers[order["customer_id"]]
    from services.loyalty import TIER_THRESHOLDS
    lifetime_pre_this_order = customer.get("lifetime_points_earned", 0) - order.get("points_provisional", 0)
    tier_at_delivery = "BRONZE"
    for name, threshold in TIER_THRESHOLDS:
        if lifetime_pre_this_order >= threshold:
            tier_at_delivery = name
            break

    order["fulfillment_status"] = "DELIVERED"

    # Flip each reserved unit to SOLD.
    lines = [l for l in DB.order_lines.values() if l["order_id"] == order["id"]]
    delivered_ts = iso_now()
    for l in lines:
        for uid in l["_reserved_stock_unit_ids"]:
            su = DB.stock_units.get(uid)
            if su and su["sale_status"] == "RESERVED":
                su["sale_status"] = "SOLD"
                bump(su)
        l["delivered_at"] = delivered_ts

    # Loyalty final accrual.
    final_points = compute_accrual_points(order["subtotal_cents"], tier_at_delivery)
    delta = final_points - order["points_provisional"]
    order["points_finalized"] = final_points
    bump(order)
    # Append LoyaltyLedger ACCRUAL_FINAL_DELTA with delta_points = delta.
    append_ledger(order["customer_id"], order["id"], "ACCRUAL_FINAL_DELTA", delta)

    return ok(delivery)


@bp.get("/deliveries")
def list_deliveries():
    role, user_id = auth_context()
    require_role(role, {"ShopStaff", "Manager", "DeliveryDriver"})
    limit, offset = parse_pagination(request.args)
    rows = list(DB.deliveries.values())
    order_id = request.args.get("order_id")
    driver_id = request.args.get("driver_id")
    if order_id:
        rows = [d for d in rows if d["order_id"] == order_id]
    if driver_id:
        rows = [d for d in rows if d["driver_id"] == driver_id]
    if role == "DeliveryDriver":
        rows = [d for d in rows if d["driver_id"] == user_id]
    rows = sort_by_created(rows)
    page, total = paginate(rows, limit, offset)
    return ok_list(page, limit=limit, offset=offset, total_count=total)


@bp.get("/deliveries/<did>")
def get_delivery(did):
    role, user_id = auth_context()
    require_role(role, {"DeliveryDriver", "ShopStaff", "Manager"})
    delivery = DB.deliveries.get(did)
    if not delivery:
        raise not_found("DeliveryAssignment")
    if role == "DeliveryDriver" and user_id != delivery["driver_id"]:
        raise unauthorized("not assigned driver")
    return ok(delivery)
