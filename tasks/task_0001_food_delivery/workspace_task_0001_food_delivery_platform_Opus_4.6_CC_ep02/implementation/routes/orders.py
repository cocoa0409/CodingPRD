from flask import Blueprint, request
from auth import require_roles, check_ownership
from errors import APIError
from models import (restaurants, customers, menu_items, orders, riders,
                    assignments, route_groups, returns as returns_store,
                    versioned_resource_base, operational_resource_base, touch, check_version)
from response_envelope import success_response
from pagination import parse_pagination_params, paginate
from calculations import (haversine_km, compute_delivery_fee, compute_tiered_commission,
                          compute_flat_commission, recompute_rider_bonus)
from datetime import timedelta
import clock

bp = Blueprint("orders", __name__)


def order_dict(o):
    return {
        "id": o["id"],
        "customer_id": o["customer_id"],
        "restaurant_id": o["restaurant_id"],
        "items": o["items"],
        "subtotal_cents": o["subtotal_cents"],
        "distance_km": o["distance_km"],
        "is_peak": o["is_peak"],
        "promised_delivery_time": o["promised_delivery_time"],
        "provisional_delivery_fee_cents": o["provisional_delivery_fee_cents"],
        "provisional_commission_cents": o["provisional_commission_cents"],
        "final_delivery_fee_cents": o["final_delivery_fee_cents"],
        "final_commission_cents": o["final_commission_cents"],
        "actual_delivery_time": o["actual_delivery_time"],
        "minutes_late": o["minutes_late"],
        "status": o["status"],
        "payment_status": o["payment_status"],
        "created_at": o["created_at"],
        "updated_at": o["updated_at"],
        "version": o["version"],
    }


def find_best_available_rider(exclude_rider_ids=None):
    exclude = exclude_rider_ids or set()
    for r in riders.values():
        if r["id"] not in exclude and r["status"] in ("AVAILABLE", "ON_DELIVERY"):
            return r
    return None


def create_dispatch_assignment(order_id, exclude_rider_ids=None):
    rider = find_best_available_rider(exclude_rider_ids)
    if not rider:
        return None

    a = operational_resource_base()
    a.update({
        "order_id": order_id,
        "rider_id": rider["id"],
        "route_group_id": None,
        "status": "OFFERED",
        "offered_at": clock.format_timestamp(clock.now()),
        "accepted_at": None,
        "picked_up_at": None,
        "delivered_at": None,
        "final_delivery_fee_cents": None,
    })
    assignments[a["id"]] = a
    return a


@bp.route("/api/orders", methods=["POST"])
@require_roles("Customer")
def place_order():
    data = request.get_json(force=True, silent=True) or {}

    customer_id = data.get("customer_id")
    if not customer_id:
        raise APIError("ERR_NOT_FOUND", "Customer not found")
    customer = customers.get(customer_id)
    if not customer:
        raise APIError("ERR_NOT_FOUND", "Customer not found")

    restaurant_id = data.get("restaurant_id")
    if not restaurant_id:
        raise APIError("ERR_NOT_FOUND", "Restaurant not found")
    restaurant = restaurants.get(restaurant_id)
    if not restaurant:
        raise APIError("ERR_NOT_FOUND", "Restaurant not found")

    items_input = data.get("items")
    resolved_items = []
    if isinstance(items_input, list):
        for item in items_input:
            if isinstance(item, dict):
                mid = item.get("menu_item_id")
                if mid:
                    mi = menu_items.get(mid)
                    if not mi:
                        raise APIError("ERR_NOT_FOUND", f"Menu item {mid} not found")
                    resolved_items.append((item, mi))

    check_ownership(customer_id, request.user_id, request.user_role, ["Customer"])

    if restaurant["status"] != "ACTIVE":
        raise APIError("ERR_RESTAURANT_UNAVAILABLE", "Restaurant is not active")

    for item, mi in resolved_items:
        if mi["restaurant_id"] != restaurant_id:
            raise APIError("ERR_RESTAURANT_UNAVAILABLE", "Menu item does not belong to this restaurant")
        if not mi["is_listed"]:
            raise APIError("ERR_RESTAURANT_UNAVAILABLE", "Menu item is not listed")

    if not items_input or not isinstance(items_input, list) or len(items_input) == 0:
        raise APIError("ERR_ORDER_INVALID", "items must be a non-empty array")

    order_items = []
    subtotal = 0
    for item, mi in resolved_items:
        quantity = item.get("quantity", 1)
        if not isinstance(quantity, int) or quantity < 1:
            raise APIError("ERR_ORDER_INVALID", "quantity must be a positive integer")

        order_items.append({
            "menu_item_id": mi["id"],
            "name": mi["name"],
            "unit_price_cents": mi["price_cents"],
            "quantity": quantity,
        })
        subtotal += mi["price_cents"] * quantity

    if subtotal < 100:
        raise APIError("ERR_ORDER_INVALID", "Order subtotal must be at least 100 cents")

    now = clock.now()
    distance = haversine_km(restaurant["lat"], restaurant["lng"], customer["lat"], customer["lng"])
    peak = clock.is_peak(now)
    promised = now + timedelta(minutes=45)

    prov_fee = compute_delivery_fee(distance, peak)
    prov_commission = compute_tiered_commission(subtotal)

    o = versioned_resource_base()
    o.update({
        "customer_id": customer_id,
        "restaurant_id": restaurant_id,
        "items": order_items,
        "subtotal_cents": subtotal,
        "distance_km": distance,
        "is_peak": peak,
        "promised_delivery_time": clock.format_timestamp(promised),
        "provisional_delivery_fee_cents": prov_fee,
        "provisional_commission_cents": prov_commission,
        "final_delivery_fee_cents": None,
        "final_commission_cents": None,
        "actual_delivery_time": None,
        "minutes_late": None,
        "status": "PLACED",
        "payment_status": "AUTHORIZED",
    })

    orders[o["id"]] = o
    return success_response(order_dict(o), 201)


@bp.route("/api/orders/<order_id>", methods=["GET"])
@require_roles("PlatformAdmin", "Customer", "Restaurant", "Rider", "CustomerService")
def get_order(order_id):
    o = orders.get(order_id)
    if not o:
        raise APIError("ERR_NOT_FOUND", "Order not found")
    return success_response(order_dict(o))


@bp.route("/api/orders", methods=["GET"])
@require_roles("PlatformAdmin", "Customer", "Restaurant", "Rider", "CustomerService")
def list_orders():
    limit, offset = parse_pagination_params(request.args)

    items = sorted(orders.values(), key=lambda x: x["created_at"])

    customer_id = request.args.get("customer_id")
    restaurant_id = request.args.get("restaurant_id")
    rider_id = request.args.get("rider_id")
    status_filter = request.args.get("status")

    if customer_id:
        items = [o for o in items if o["customer_id"] == customer_id]
    if restaurant_id:
        items = [o for o in items if o["restaurant_id"] == restaurant_id]
    if rider_id:
        order_ids_for_rider = set()
        for a in assignments.values():
            if a["rider_id"] == rider_id:
                order_ids_for_rider.add(a["order_id"])
        items = [o for o in items if o["id"] in order_ids_for_rider]
    if status_filter:
        items = [o for o in items if o["status"] == status_filter]

    page, pagination = paginate(items, limit, offset)
    return success_response([order_dict(o) for o in page], 200, "array", pagination)


@bp.route("/api/orders/<order_id>/accept", methods=["POST"])
@require_roles("Restaurant")
def accept_order(order_id):
    o = orders.get(order_id)
    if not o:
        raise APIError("ERR_NOT_FOUND", "Order not found")

    check_ownership(o["restaurant_id"], request.user_id, request.user_role, ["Restaurant"])

    if o["status"] != "PLACED":
        raise APIError("ERR_INVALID_STATE", "Order must be in PLACED to accept")

    restaurant = restaurants.get(o["restaurant_id"])
    if not restaurant or restaurant["status"] != "ACTIVE":
        raise APIError("ERR_INVALID_STATE", "Restaurant is not active")

    o["status"] = "RESTAURANT_ACCEPTED"
    touch(o)
    return success_response(order_dict(o))


@bp.route("/api/orders/<order_id>/cancel", methods=["POST"])
@require_roles("Customer", "Restaurant", "CustomerService")
def cancel_order(order_id):
    o = orders.get(order_id)
    if not o:
        raise APIError("ERR_NOT_FOUND", "Order not found")

    if request.user_role == "Customer":
        check_ownership(o["customer_id"], request.user_id, request.user_role, ["Customer"])
    elif request.user_role == "Restaurant":
        check_ownership(o["restaurant_id"], request.user_id, request.user_role, ["Restaurant"])

    if o["status"] != "PLACED":
        raise APIError("ERR_INVALID_STATE", "Order must be in PLACED to cancel")

    o["status"] = "CANCELLED"
    if o["payment_status"] in ("UNPAID", "AUTHORIZED"):
        o["payment_status"] = "VOIDED"
    touch(o)
    return success_response(order_dict(o))


@bp.route("/api/orders/<order_id>/start-preparing", methods=["POST"])
@require_roles("Restaurant")
def start_preparing(order_id):
    o = orders.get(order_id)
    if not o:
        raise APIError("ERR_NOT_FOUND", "Order not found")

    check_ownership(o["restaurant_id"], request.user_id, request.user_role, ["Restaurant"])

    if o["status"] != "RESTAURANT_ACCEPTED":
        raise APIError("ERR_INVALID_STATE", "Order must be in RESTAURANT_ACCEPTED to start preparing")

    o["status"] = "PREPARING"
    touch(o)

    create_dispatch_assignment(order_id)

    return success_response(order_dict(o))


@bp.route("/api/orders/<order_id>/ready", methods=["POST"])
@require_roles("Restaurant")
def mark_ready(order_id):
    o = orders.get(order_id)
    if not o:
        raise APIError("ERR_NOT_FOUND", "Order not found")

    check_ownership(o["restaurant_id"], request.user_id, request.user_role, ["Restaurant"])

    if o["status"] != "PREPARING":
        raise APIError("ERR_INVALID_STATE", "Order must be in PREPARING to mark ready")

    has_accepted_rider = False
    for a in assignments.values():
        if a["order_id"] == order_id and a["status"] in ("ACCEPTED", "PICKED_UP"):
            has_accepted_rider = True
            break

    if not has_accepted_rider:
        raise APIError("ERR_INVALID_STATE", "A rider must have accepted before marking ready")

    o["status"] = "READY_FOR_PICKUP"
    touch(o)
    return success_response(order_dict(o))


@bp.route("/api/orders/<order_id>/dispatch", methods=["POST"])
@require_roles("PlatformAdmin", "CustomerService")
def dispatch_order(order_id):
    o = orders.get(order_id)
    if not o:
        raise APIError("ERR_NOT_FOUND", "Order not found")

    a = create_dispatch_assignment(order_id)
    if not a:
        return success_response(order_dict(o))

    from routes.assignments import assignment_dict
    return success_response(assignment_dict(a), 201)


@bp.route("/api/orders/<order_id>/returns", methods=["POST"])
@require_roles("Customer")
def open_return(order_id):
    o = orders.get(order_id)
    if not o:
        raise APIError("ERR_NOT_FOUND", "Order not found")

    check_ownership(o["customer_id"], request.user_id, request.user_role, ["Customer"])

    if o["status"] != "DELIVERED":
        raise APIError("ERR_INVALID_STATE", "Order must be in DELIVERED to open a return")

    for ret in returns_store.values():
        if ret["order_id"] == order_id and ret["status"] in ("REQUESTED", "APPROVED", "ESCALATED"):
            raise APIError("ERR_DUPLICATE_RETURN", "A return already exists for this order")

    if o["actual_delivery_time"]:
        from datetime import datetime, timezone
        delivery_time = datetime.fromisoformat(o["actual_delivery_time"].replace("Z", "+00:00"))
        now = clock.now()
        hours_since = (now - delivery_time).total_seconds() / 3600
        if hours_since > 24:
            raise APIError("ERR_RETURN_WINDOW_EXPIRED", "Return window has expired (24 hours)")

    data = request.get_json(force=True, silent=True) or {}

    requested_refund_cents = data.get("requested_refund_cents")
    if requested_refund_cents is None or not isinstance(requested_refund_cents, int):
        raise APIError("ERR_VALIDATION", "requested_refund_cents must be an integer")
    if requested_refund_cents < 1 or requested_refund_cents > o["subtotal_cents"]:
        raise APIError("ERR_REFUND_AMOUNT_INVALID",
                        "requested_refund_cents must be between 1 and subtotal_cents")

    reason = data.get("reason")
    valid_reasons = {"QUALITY_ISSUE", "WRONG_ITEM", "LATE", "OTHER"}
    if not reason or reason not in valid_reasons:
        raise APIError("ERR_VALIDATION", "reason must be one of QUALITY_ISSUE, WRONG_ITEM, LATE, OTHER")

    from models import versioned_resource_base
    ret = versioned_resource_base()
    ret.update({
        "order_id": order_id,
        "reason": reason,
        "requested_refund_cents": requested_refund_cents,
        "approved_refund_cents": None,
        "reviewer_cs_user_id": None,
        "status": "REQUESTED",
    })

    returns_store[ret["id"]] = ret

    o["status"] = "REFUND_REQUESTED"
    touch(o)

    from routes.returns_ import return_dict
    return success_response(return_dict(ret), 201)
