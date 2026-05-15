"""Order endpoints + payment/logistics event ingress."""
from __future__ import annotations

import copy
from datetime import timedelta

from flask import Blueprint, request

from app.audit import append_audit
from app.auth import assert_customer_owns, require_role
from app.clock import logical_clock
from app.errors import api_error
from app.pagination import paginate, parse_pagination, sort_by_created_at
from app.response import success_array, success_object
from app.services.orders import (
    cancel_order_fulfillment,
    debit_warehouse_capacity,
    select_lots_for_order,
    select_warehouse_for_order,
)
from app.store import store
from app.utils import (
    format_iso,
    is_int,
    is_nonempty_str,
    logical_now_iso,
    parse_iso,
    utc_date_key,
)


bp = Blueprint("orders", __name__)


def _ensure_order(order_id, user_id, role):
    order = store.orders.get(order_id)
    if not order:
        raise api_error("ERR_ORDER_NOT_FOUND", "Order not found")
    if role == "Customer":
        assert_customer_owns(order["customer_id"], user_id, role)
    return order


@bp.route("/subscriptions/<sub_id>/orders", methods=["GET"])
@require_role("Customer", "AdminOps")
def list_subscription_orders(sub_id, user_id: str, role: str):
    sub = store.subscriptions.get(sub_id)
    if not sub:
        raise api_error("ERR_SUBSCRIPTION_NOT_FOUND", "Subscription not found")
    if role == "Customer":
        assert_customer_owns(sub["customer_id"], user_id, role)
    limit, offset = parse_pagination()
    f_filter = request.args.get("fulfillment_status")
    p_filter = request.args.get("payment_status")
    items = [
        o
        for o in store.orders.values()
        if o["subscription_id"] == sub_id
        and (not f_filter or o.get("fulfillment_status") == f_filter)
        and (not p_filter or o.get("payment_status") == p_filter)
    ]
    items = sort_by_created_at(items)
    page, total = paginate(items, limit, offset)
    return success_array(page, limit, offset, total)


@bp.route("/orders/<order_id>", methods=["GET"])
@require_role("Customer", "AdminOps")
def get_order(order_id, user_id: str, role: str):
    order = _ensure_order(order_id, user_id, role)
    return success_object(order)


@bp.route("/orders/<order_id>/confirm", methods=["POST"])
@require_role("Customer")
def confirm(order_id, user_id: str, role: str):
    order = _ensure_order(order_id, user_id, role)
    sub = store.subscriptions.get(order["subscription_id"])
    if not sub or sub.get("status") != "ACTIVE":
        raise api_error("ERR_INVALID_SUBSCRIPTION_STATE", "Subscription not ACTIVE")
    if order["fulfillment_status"] != "SCHEDULED":
        raise api_error("ERR_INVALID_ORDER_STATE", "Order not SCHEDULED")

    # Refresh snapshot from current subscription address at confirmation time.
    snap = copy.deepcopy(sub.get("shipping_address") or {})
    order["shipping_address_snapshot"] = snap
    if not bool(snap.get("verified", False)):
        raise api_error("ERR_ADDRESS_NOT_VERIFIED", "Shipping address not verified")

    warehouse = select_warehouse_for_order(order)
    # Capacity check up-front; lots will decrement during selection
    ship_at = parse_iso(order["scheduled_ship_at"])
    date_key = utc_date_key(ship_at)
    used = store.warehouse_daily_used.get(warehouse["id"], {}).get(date_key, 0)
    if used >= int(warehouse["daily_outbound_capacity"]):
        raise api_error("ERR_WAREHOUSE_CAPACITY_EXCEEDED", "Warehouse daily capacity reached")

    assigned = select_lots_for_order(order, warehouse)
    order["warehouse_id"] = warehouse["id"]
    order["assigned_lots"] = assigned
    order["fulfillment_status"] = "CONFIRMED"
    order["updated_at"] = logical_now_iso()
    order["version"] = order.get("version", 1) + 1
    debit_warehouse_capacity(warehouse["id"], date_key)
    return success_object(order)


@bp.route("/orders/<order_id>/skip", methods=["POST"])
@require_role("Customer")
def skip(order_id, user_id: str, role: str):
    order = _ensure_order(order_id, user_id, role)
    sub = store.subscriptions.get(order["subscription_id"])
    if not sub:
        raise api_error("ERR_SUBSCRIPTION_NOT_FOUND", "Subscription not found")
    if sub.get("status") != "ACTIVE":
        raise api_error("ERR_INVALID_SUBSCRIPTION_STATE", "Subscription not ACTIVE")
    if order["fulfillment_status"] != "SCHEDULED":
        raise api_error("ERR_INVALID_ORDER_STATE", "Order not SCHEDULED")

    ship_at = parse_iso(order["scheduled_ship_at"])
    cutoff = ship_at - timedelta(hours=int(sub["modification_deadline_hours"]))
    if logical_clock.now() >= cutoff:
        raise api_error("ERR_MODIFICATION_DEADLINE_PASSED", "Past modification deadline")

    before = {"fulfillment_status": "SCHEDULED"}
    order["fulfillment_status"] = "SKIPPED"
    order["updated_at"] = logical_now_iso()
    order["version"] = order.get("version", 1) + 1

    # Counter adjustments
    sub["scheduled_order_count"] = max(0, sub["scheduled_order_count"] - 1)
    sub["skipped_count"] += 1
    # total_cycles_elapsed unchanged
    # Advance next_cycle_at by cycle_days
    if sub.get("next_cycle_at"):
        cur = parse_iso(sub["next_cycle_at"])
        sub["next_cycle_at"] = format_iso(cur + timedelta(days=int(sub["cycle_days"])))
    else:
        sub["next_cycle_at"] = format_iso(logical_clock.now() + timedelta(days=int(sub["cycle_days"])))
    sub["updated_at"] = logical_now_iso()
    sub["version"] = sub.get("version", 1) + 1

    append_audit(
        actor_role=role,
        actor_id=user_id,
        entity_type="Order",
        entity_id=order_id,
        event_type="SKIPPED",
        before=before,
        after={"fulfillment_status": "SKIPPED"},
    )
    return success_object(order)


# ----------------- Payment event ingress -----------------


@bp.route("/orders/<order_id>/events/payment", methods=["POST"])
@require_role("PaymentAdapter")
def payment_event(order_id, user_id: str, role: str):
    order = store.orders.get(order_id)
    if not order:
        raise api_error("ERR_ORDER_NOT_FOUND", "Order not found")
    body = request.get_json(silent=True) or {}
    if not isinstance(body, dict):
        raise api_error("ERR_INVALID_REQUEST", "Body must be JSON object")
    event_type = body.get("event_type")
    if event_type not in ("PAYMENT_CAPTURED", "PAYMENT_FAILED", "PAYMENT_REFUNDED"):
        raise api_error("ERR_INVALID_REQUEST", "Unknown payment event_type")

    customer = store.customers.get(order["customer_id"])

    if event_type == "PAYMENT_CAPTURED":
        if order["payment_status"] != "PENDING":
            raise api_error("ERR_INVALID_ORDER_STATE", "Not PENDING")
        if order["fulfillment_status"] not in ("SCHEDULED", "CONFIRMED"):
            raise api_error("ERR_INVALID_ORDER_STATE", "Fulfillment not SCHEDULED/CONFIRMED")
        order["payment_status"] = "PAID"
        if customer:
            customer["total_charged_cents"] = int(customer.get("total_charged_cents", 0)) + int(order["total_cents"])
            customer["updated_at"] = logical_now_iso()
            customer["version"] = customer.get("version", 1) + 1
    elif event_type == "PAYMENT_FAILED":
        if order["payment_status"] != "PENDING":
            raise api_error("ERR_INVALID_ORDER_STATE", "Not PENDING")
        order["payment_status"] = "FAILED"
        if order["fulfillment_status"] in ("SCHEDULED", "CONFIRMED"):
            cancel_order_fulfillment(order)
    else:  # PAYMENT_REFUNDED
        if order["payment_status"] != "PAID":
            raise api_error("ERR_INVALID_ORDER_STATE", "Not PAID")
        if order["fulfillment_status"] != "CANCELLED":
            raise api_error("ERR_INVALID_ORDER_STATE", "Fulfillment not CANCELLED")
        order["payment_status"] = "REFUNDED"
        if customer:
            customer["total_refunded_cents"] = int(customer.get("total_refunded_cents", 0)) + int(order["total_cents"])
            customer["updated_at"] = logical_now_iso()
            customer["version"] = customer.get("version", 1) + 1

    order["updated_at"] = logical_now_iso()
    order["version"] = order.get("version", 1) + 1
    return success_object(order)


# ----------------- Logistics event ingress -----------------


@bp.route("/orders/<order_id>/events/logistics", methods=["POST"])
@require_role("LogisticsAdapter")
def logistics_event(order_id, user_id: str, role: str):
    order = store.orders.get(order_id)
    if not order:
        raise api_error("ERR_ORDER_NOT_FOUND", "Order not found")
    body = request.get_json(silent=True) or {}
    if not isinstance(body, dict):
        raise api_error("ERR_INVALID_REQUEST", "Body must be JSON object")
    event_type = body.get("event_type")
    if event_type not in ("SHIPMENT_DISPATCHED", "DELIVERY_CONFIRMED"):
        raise api_error("ERR_INVALID_REQUEST", "Unknown logistics event_type")

    if event_type == "SHIPMENT_DISPATCHED":
        if order["fulfillment_status"] != "CONFIRMED":
            raise api_error("ERR_INVALID_ORDER_STATE", "Not CONFIRMED")
        if order["payment_status"] != "PAID":
            raise api_error("ERR_INVALID_ORDER_STATE", "Not PAID")
        tracking = body.get("tracking_number")
        if tracking is not None and not is_nonempty_str(tracking):
            raise api_error("ERR_INVALID_REQUEST", "tracking_number must be string")
        order["fulfillment_status"] = "SHIPPED"
        order["tracking_number"] = tracking
    else:  # DELIVERY_CONFIRMED
        if order["fulfillment_status"] != "SHIPPED":
            raise api_error("ERR_INVALID_ORDER_STATE", "Not SHIPPED")
        order["fulfillment_status"] = "DELIVERED"

    order["updated_at"] = logical_now_iso()
    order["version"] = order.get("version", 1) + 1
    return success_object(order)
