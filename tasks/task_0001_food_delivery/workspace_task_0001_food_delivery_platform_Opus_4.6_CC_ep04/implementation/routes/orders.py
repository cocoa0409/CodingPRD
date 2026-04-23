import math
from datetime import timedelta
from flask import Blueprint, request
from middleware.auth import require_roles
from storage import db
from models.order import Order
from models.base import now_ts
from response import success_response
from errors import (raise_error, ERR_NOT_FOUND, ERR_FORBIDDEN, ERR_INVALID_STATE,
                    ERR_VALIDATION, ERR_RESTAURANT_UNAVAILABLE, ERR_ORDER_INVALID,
                    ERR_RETURN_WINDOW_EXPIRED, ERR_REFUND_AMOUNT_INVALID, ERR_DUPLICATE_RETURN)
from services.commission import compute_tiered_commission
from services.delivery_fee import compute_delivery_fee
from services.dispatch import haversine_km, dispatch_order

bp = Blueprint("orders", __name__)


def get_order_or_404(order_id):
    o = db.orders.get(order_id)
    if not o:
        raise_error(ERR_NOT_FOUND, "Order not found.")
    return o


def is_peak(ts):
    hour = ts.hour
    return (11 <= hour < 13) or (18 <= hour < 20)


@bp.route("/api/orders", methods=["POST"])
@require_roles("Customer")
def place_order():
    data = request.get_json(force=True, silent=True) or {}
    customer_id = data.get("customer_id")
    restaurant_id = data.get("restaurant_id")
    items = data.get("items")

    if not customer_id:
        raise_error(ERR_VALIDATION, "customer_id is required.")
    customer = db.customers.get(customer_id)
    if not customer:
        raise_error(ERR_NOT_FOUND, "Customer not found.")
    if not restaurant_id:
        raise_error(ERR_VALIDATION, "restaurant_id is required.")
    restaurant = db.restaurants.get(restaurant_id)
    if not restaurant:
        raise_error(ERR_NOT_FOUND, "Restaurant not found.")

    if request.user_id != customer_id:
        raise_error(ERR_FORBIDDEN, "Cannot place an order for another customer.")

    if restaurant.status != "ACTIVE":
        raise_error(ERR_RESTAURANT_UNAVAILABLE, "Restaurant is not active.")

    if not items or not isinstance(items, list) or len(items) == 0:
        raise_error(ERR_ORDER_INVALID, "Items must be a non-empty array.")

    order_items = []
    subtotal = 0
    for item_data in items:
        menu_item_id = item_data.get("menu_item_id")
        quantity = item_data.get("quantity")

        if not menu_item_id:
            raise_error(ERR_VALIDATION, "menu_item_id is required for each item.")
        mi = db.menu_items.get(menu_item_id)
        if not mi:
            raise_error(ERR_NOT_FOUND, f"Menu item {menu_item_id} not found.")
        if mi.restaurant_id != restaurant_id:
            raise_error(ERR_RESTAURANT_UNAVAILABLE, "Menu item does not belong to this restaurant.")
        if not mi.is_listed:
            raise_error(ERR_RESTAURANT_UNAVAILABLE, "Menu item is not listed.")

        if quantity is None or not isinstance(quantity, int) or quantity < 1:
            raise_error(ERR_ORDER_INVALID, "Each item quantity must be >= 1.")

        order_items.append({
            "menu_item_id": mi.id,
            "name": mi.name,
            "unit_price_cents": mi.price_cents,
            "quantity": quantity,
        })
        subtotal += mi.price_cents * quantity

    if subtotal < 100:
        raise_error(ERR_ORDER_INVALID, "Subtotal must be at least 100 cents.")

    placement_time = now_ts()
    peak = is_peak(placement_time)
    distance = haversine_km(restaurant.lat, restaurant.lng, customer.lat, customer.lng)
    distance_km = round(distance, 1)
    promised = placement_time + timedelta(minutes=45)

    prov_fee = compute_delivery_fee(distance_km, peak)
    prov_commission = compute_tiered_commission(subtotal)

    order = Order(
        customer_id=customer_id,
        restaurant_id=restaurant_id,
        items=order_items,
        subtotal_cents=subtotal,
        distance_km=distance_km,
        is_peak=peak,
        promised_delivery_time=promised,
        provisional_delivery_fee_cents=prov_fee,
        provisional_commission_cents=prov_commission,
    )
    db.orders[order.id] = order
    return success_response(order.to_dict(), 201)


@bp.route("/api/orders/<order_id>", methods=["GET"])
@require_roles("PlatformAdmin", "Customer", "Restaurant", "Rider", "CustomerService")
def get_order(order_id):
    o = get_order_or_404(order_id)
    return success_response(o.to_dict())


@bp.route("/api/orders", methods=["GET"])
@require_roles("PlatformAdmin", "Customer", "Restaurant", "Rider", "CustomerService")
def list_orders():
    customer_id_filter = request.args.get("customer_id")
    restaurant_id_filter = request.args.get("restaurant_id")
    rider_id_filter = request.args.get("rider_id")
    status_filter = request.args.get("status")
    limit = request.args.get("limit", 10, type=int)
    offset = request.args.get("offset", 0, type=int)

    if limit < 1 or limit > 100:
        raise_error(ERR_VALIDATION, "limit must be between 1 and 100.")
    if offset < 0:
        raise_error(ERR_VALIDATION, "offset must be >= 0.")

    items = sorted(db.orders.values(), key=lambda o: o.created_at)
    if customer_id_filter:
        items = [o for o in items if o.customer_id == customer_id_filter]
    if restaurant_id_filter:
        items = [o for o in items if o.restaurant_id == restaurant_id_filter]
    if status_filter:
        items = [o for o in items if o.status == status_filter]
    if rider_id_filter:
        order_ids_for_rider = {
            a.order_id for a in db.assignments.values()
            if a.rider_id == rider_id_filter and a.status in ("ACCEPTED", "PICKED_UP", "DELIVERED")
        }
        items = [o for o in items if o.id in order_ids_for_rider]

    total_count = len(items)
    page = items[offset:offset + limit]
    return success_response(
        [o.to_dict() for o in page],
        pagination={
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": offset + limit < total_count,
        },
    )


@bp.route("/api/orders/<order_id>/accept", methods=["POST"])
@require_roles("Restaurant")
def accept_order(order_id):
    o = get_order_or_404(order_id)
    restaurant = db.restaurants.get(o.restaurant_id)
    if not restaurant:
        raise_error(ERR_NOT_FOUND, "Restaurant not found.")
    if request.user_id != o.restaurant_id:
        raise_error(ERR_FORBIDDEN, "Cannot accept another restaurant's order.")
    if o.status != "PLACED":
        raise_error(ERR_INVALID_STATE, "Order must be in PLACED state to accept.")
    if restaurant.status != "ACTIVE":
        raise_error(ERR_RESTAURANT_UNAVAILABLE, "Restaurant is not active.")
    o.status = "RESTAURANT_ACCEPTED"
    o.touch()
    return success_response(o.to_dict())


@bp.route("/api/orders/<order_id>/cancel", methods=["POST"])
@require_roles("Customer", "Restaurant", "CustomerService")
def cancel_order(order_id):
    o = get_order_or_404(order_id)
    if request.user_role == "Customer" and request.user_id != o.customer_id:
        raise_error(ERR_FORBIDDEN, "Cannot cancel another customer's order.")
    if request.user_role == "Restaurant" and request.user_id != o.restaurant_id:
        raise_error(ERR_FORBIDDEN, "Cannot cancel another restaurant's order.")
    if o.status != "PLACED":
        raise_error(ERR_INVALID_STATE, "Order must be in PLACED state to cancel.")
    o.status = "CANCELLED"
    if o.payment_status in ("UNPAID", "AUTHORIZED"):
        o.payment_status = "VOIDED"
    o.touch()
    return success_response(o.to_dict())


@bp.route("/api/orders/<order_id>/start-preparing", methods=["POST"])
@require_roles("Restaurant")
def start_preparing(order_id):
    o = get_order_or_404(order_id)
    if request.user_id != o.restaurant_id:
        raise_error(ERR_FORBIDDEN, "Cannot modify another restaurant's order.")
    if o.status != "RESTAURANT_ACCEPTED":
        raise_error(ERR_INVALID_STATE, "Order must be in RESTAURANT_ACCEPTED state.")
    o.status = "PREPARING"
    o.touch()
    dispatch_order(o.id)
    return success_response(o.to_dict())


@bp.route("/api/orders/<order_id>/ready", methods=["POST"])
@require_roles("Restaurant")
def mark_ready(order_id):
    o = get_order_or_404(order_id)
    if request.user_id != o.restaurant_id:
        raise_error(ERR_FORBIDDEN, "Cannot modify another restaurant's order.")
    if o.status != "PREPARING":
        raise_error(ERR_INVALID_STATE, "Order must be in PREPARING state.")

    has_accepted_rider = any(
        a for a in db.assignments.values()
        if a.order_id == o.id and a.status in ("ACCEPTED", "PICKED_UP")
    )
    if not has_accepted_rider:
        raise_error(ERR_INVALID_STATE, "No rider has accepted the dispatch yet.")

    o.status = "READY_FOR_PICKUP"
    o.touch()
    return success_response(o.to_dict())


@bp.route("/api/orders/<order_id>/dispatch", methods=["POST"])
@require_roles("PlatformAdmin", "CustomerService")
def manual_dispatch(order_id):
    o = get_order_or_404(order_id)
    tried = {a.rider_id for a in db.assignments.values() if a.order_id == o.id}
    assignment = dispatch_order(o.id, exclude_rider_ids=tried)
    if not assignment:
        raise_error(ERR_VALIDATION, "No available rider for dispatch.")
    return success_response(assignment.to_dict(), 201)


@bp.route("/api/orders/<order_id>/returns", methods=["POST"])
@require_roles("Customer")
def open_return(order_id):
    o = get_order_or_404(order_id)
    if request.user_id != o.customer_id:
        raise_error(ERR_FORBIDDEN, "Cannot open a return for another customer's order.")
    if o.status != "DELIVERED":
        raise_error(ERR_INVALID_STATE, "Order must be in DELIVERED state to open a return.")

    current_time = now_ts()
    if o.actual_delivery_time:
        elapsed = (current_time - o.actual_delivery_time).total_seconds()
        if elapsed > 24 * 3600:
            raise_error(ERR_RETURN_WINDOW_EXPIRED, "Return window has expired (24 hours).")

    data = request.get_json(force=True, silent=True) or {}
    reason = data.get("reason")
    requested_refund_cents = data.get("requested_refund_cents")

    valid_reasons = {"QUALITY_ISSUE", "WRONG_ITEM", "LATE", "OTHER"}
    if reason not in valid_reasons:
        raise_error(ERR_VALIDATION, "Invalid return reason.")

    if requested_refund_cents is None or not isinstance(requested_refund_cents, int):
        raise_error(ERR_VALIDATION, "requested_refund_cents is required and must be an integer.")
    if requested_refund_cents < 1 or requested_refund_cents > o.subtotal_cents:
        raise_error(ERR_REFUND_AMOUNT_INVALID, "Requested refund must be between 1 and subtotal_cents.")

    existing = any(
        r for r in db.returns.values()
        if r.order_id == o.id and r.status in ("REQUESTED", "APPROVED", "ESCALATED")
    )
    if existing:
        raise_error(ERR_DUPLICATE_RETURN, "A return already exists for this order.")

    from models.return_model import Return
    ret = Return(o.id, reason, requested_refund_cents)
    db.returns[ret.id] = ret
    o.status = "REFUND_REQUESTED"
    o.touch()
    return success_response(ret.to_dict(), 201)
