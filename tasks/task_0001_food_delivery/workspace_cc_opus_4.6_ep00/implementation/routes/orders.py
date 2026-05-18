from flask import Blueprint, request
from store import store
from models import make_versioned, touch, serialize
from middleware import check_role_permission
from response import success_response
from pagination import get_pagination_params, paginate
from clock import now, format_timestamp
from datetime import timedelta
from errors import (
    raise_error, ERR_FORBIDDEN, ERR_NOT_FOUND, ERR_INVALID_STATE,
    ERR_VALIDATION, ERR_ORDER_INVALID, ERR_RESTAURANT_UNAVAILABLE,
)
from services.computations import (
    haversine_km, is_peak_time, compute_delivery_fee,
    compute_tiered_commission,
)

bp = Blueprint("orders", __name__)


@bp.route("/api/orders", methods=["POST"])
def place_order():
    check_role_permission({"Customer"})
    data = request.get_json(force=True, silent=True) or {}

    # Step 4: FK existence checks
    customer_id = data.get("customer_id")
    customer = store.customers.get(customer_id) if customer_id else None
    if customer_id and not customer:
        raise_error(ERR_NOT_FOUND, "Customer not found")

    restaurant_id = data.get("restaurant_id")
    restaurant = store.restaurants.get(restaurant_id) if restaurant_id else None
    if restaurant_id and not restaurant:
        raise_error(ERR_NOT_FOUND, "Restaurant not found")

    # Step 4 continued: menu item FK existence
    items_raw = data.get("items")
    resolved_items = []
    if isinstance(items_raw, list):
        for entry in items_raw:
            if not isinstance(entry, dict):
                continue
            menu_item_id = entry.get("menu_item_id")
            if menu_item_id:
                mi = store.menu_items.get(menu_item_id)
                if not mi:
                    raise_error(ERR_NOT_FOUND, f"Menu item {menu_item_id} not found")
                resolved_items.append((entry, mi))
            else:
                resolved_items.append((entry, None))

    # Step 5: Identity match
    if customer_id and request.user_id != customer_id:
        raise_error(ERR_FORBIDDEN, "Cannot place order for another customer")

    # Step 7: Domain-specific checks
    if restaurant and restaurant["status"] != "ACTIVE":
        raise_error(ERR_RESTAURANT_UNAVAILABLE, "Restaurant is not active")

    for entry, mi in resolved_items:
        if mi:
            if mi["restaurant_id"] != restaurant_id:
                raise_error(ERR_RESTAURANT_UNAVAILABLE, "Menu item does not belong to this restaurant")
            if not mi["is_listed"]:
                raise_error(ERR_RESTAURANT_UNAVAILABLE, "Menu item is not listed")

    # Step 11: Shape-of-input validation
    if not customer_id:
        raise_error(ERR_VALIDATION, "customer_id is required")
    if not restaurant_id:
        raise_error(ERR_VALIDATION, "restaurant_id is required")
    if not items_raw or not isinstance(items_raw, list) or len(items_raw) == 0:
        raise_error(ERR_ORDER_INVALID, "items must be a non-empty array")

    order_items = []
    for entry, mi in resolved_items:
        if not mi:
            raise_error(ERR_VALIDATION, "menu_item_id is required in each item")
        quantity = entry.get("quantity", 1)
        if not isinstance(quantity, int) or quantity < 1:
            raise_error(ERR_ORDER_INVALID, "quantity must be >= 1")
        order_items.append({
            "menu_item_id": entry["menu_item_id"],
            "name": mi["name"],
            "unit_price_cents": mi["price_cents"],
            "quantity": quantity,
        })

    subtotal_cents = sum(i["unit_price_cents"] * i["quantity"] for i in order_items)
    if subtotal_cents < 100:
        raise_error(ERR_ORDER_INVALID, "Minimum order size is 100 cents")

    placement_time = now()
    distance_km = haversine_km(restaurant["lat"], restaurant["lng"], customer["lat"], customer["lng"])
    peak = is_peak_time(placement_time)
    provisional_fee = compute_delivery_fee(distance_km, peak)
    provisional_commission = compute_tiered_commission(subtotal_cents)
    promised_delivery_time = format_timestamp(placement_time + timedelta(minutes=45))

    credit_applied = 0
    if customer["credit_balance_cents"] > 0:
        order_total = subtotal_cents + provisional_fee
        credit_applied = min(customer["credit_balance_cents"], order_total)
        customer["credit_balance_cents"] -= credit_applied
        touch(customer)

    order = make_versioned({
        "customer_id": customer_id,
        "restaurant_id": restaurant_id,
        "rider_id": None,
        "items": order_items,
        "subtotal_cents": subtotal_cents,
        "distance_km": distance_km,
        "is_peak": peak,
        "promised_delivery_time": promised_delivery_time,
        "provisional_delivery_fee_cents": provisional_fee,
        "final_delivery_fee_cents": None,
        "provisional_commission_cents": provisional_commission,
        "final_commission_cents": None,
        "actual_delivery_time": None,
        "minutes_late": None,
        "status": "PLACED",
        "payment_status": "AUTHORIZED",
    })
    order["_promised_dt"] = placement_time + timedelta(minutes=45)
    order["_credit_applied_cents"] = credit_applied
    store.orders[order["id"]] = order
    return success_response(serialize(order), 201)


@bp.route("/api/orders/<order_id>", methods=["GET"])
def get_order(order_id):
    check_role_permission({"PlatformAdmin", "Customer", "Restaurant", "Rider", "CustomerService"})
    order = store.orders.get(order_id)
    if not order:
        raise_error(ERR_NOT_FOUND, "Order not found")

    role = request.user_role
    uid = request.user_id
    if role == "Customer" and order["customer_id"] != uid:
        raise_error(ERR_FORBIDDEN, "Cannot view another customer's order")
    if role == "Restaurant" and order["restaurant_id"] != uid:
        raise_error(ERR_FORBIDDEN, "Cannot view another restaurant's order")
    if role == "Rider" and order.get("rider_id") != uid:
        has_assignment = any(
            a["order_id"] == order_id and a["rider_id"] == uid
            for a in store.assignments.values()
        )
        if not has_assignment:
            raise_error(ERR_FORBIDDEN, "Cannot view this order")

    return success_response(serialize(order))


@bp.route("/api/orders", methods=["GET"])
def list_orders():
    check_role_permission({"PlatformAdmin", "Customer", "Restaurant", "Rider", "CustomerService"})
    limit, offset = get_pagination_params()

    items = sorted(store.orders.values(), key=lambda o: o["created_at"])

    customer_id_filter = request.args.get("customer_id")
    restaurant_id_filter = request.args.get("restaurant_id")
    rider_id_filter = request.args.get("rider_id")
    status_filter = request.args.get("status")

    if request.user_role == "Customer":
        items = [o for o in items if o["customer_id"] == request.user_id]
    elif request.user_role == "Restaurant":
        items = [o for o in items if o["restaurant_id"] == request.user_id]
    elif request.user_role == "Rider":
        items = [o for o in items if o.get("rider_id") == request.user_id]

    if customer_id_filter:
        items = [o for o in items if o["customer_id"] == customer_id_filter]
    if restaurant_id_filter:
        items = [o for o in items if o["restaurant_id"] == restaurant_id_filter]
    if rider_id_filter:
        items = [o for o in items if o.get("rider_id") == rider_id_filter]
    if status_filter:
        items = [o for o in items if o["status"] == status_filter]

    page, pagination_meta = paginate(items, limit, offset)
    return success_response([serialize(o) for o in page], 200, pagination_meta)


@bp.route("/api/orders/<order_id>/accept", methods=["POST"])
def accept_order(order_id):
    check_role_permission({"Restaurant"})
    order = store.orders.get(order_id)
    if not order:
        raise_error(ERR_NOT_FOUND, "Order not found")

    restaurant = store.restaurants.get(order["restaurant_id"])
    if not restaurant:
        raise_error(ERR_NOT_FOUND, "Restaurant not found")

    if request.user_id != order["restaurant_id"]:
        raise_error(ERR_FORBIDDEN, "Cannot accept order for another restaurant")

    if order["status"] != "PLACED":
        raise_error(ERR_INVALID_STATE, "Order must be PLACED to accept")

    if restaurant["status"] != "ACTIVE":
        raise_error(ERR_RESTAURANT_UNAVAILABLE, "Restaurant is not active")

    order["status"] = "RESTAURANT_ACCEPTED"
    touch(order)
    return success_response(serialize(order))


@bp.route("/api/orders/<order_id>/cancel", methods=["POST"])
def cancel_order(order_id):
    check_role_permission({"Customer", "Restaurant", "CustomerService"})
    order = store.orders.get(order_id)
    if not order:
        raise_error(ERR_NOT_FOUND, "Order not found")

    if request.user_role == "Customer" and request.user_id != order["customer_id"]:
        raise_error(ERR_FORBIDDEN, "Cannot cancel another customer's order")
    if request.user_role == "Restaurant" and request.user_id != order["restaurant_id"]:
        raise_error(ERR_FORBIDDEN, "Cannot cancel another restaurant's order")

    if order["status"] != "PLACED":
        raise_error(ERR_INVALID_STATE, "Order must be PLACED to cancel")

    order["status"] = "CANCELLED"
    if order["payment_status"] in ("UNPAID", "AUTHORIZED"):
        order["payment_status"] = "VOIDED"
    touch(order)
    return success_response(serialize(order))


@bp.route("/api/orders/<order_id>/start-preparing", methods=["POST"])
def start_preparing(order_id):
    check_role_permission({"Restaurant"})
    order = store.orders.get(order_id)
    if not order:
        raise_error(ERR_NOT_FOUND, "Order not found")

    if request.user_id != order["restaurant_id"]:
        raise_error(ERR_FORBIDDEN, "Cannot prepare for another restaurant")

    if order["status"] != "RESTAURANT_ACCEPTED":
        raise_error(ERR_INVALID_STATE, "Order must be RESTAURANT_ACCEPTED to start preparing")

    order["status"] = "PREPARING"
    touch(order)

    from services.dispatch import dispatch_order
    dispatch_order(order)

    return success_response(serialize(order))


@bp.route("/api/orders/<order_id>/ready", methods=["POST"])
def mark_ready(order_id):
    check_role_permission({"Restaurant"})
    order = store.orders.get(order_id)
    if not order:
        raise_error(ERR_NOT_FOUND, "Order not found")

    if request.user_id != order["restaurant_id"]:
        raise_error(ERR_FORBIDDEN, "Cannot mark ready for another restaurant")

    if order["status"] != "PREPARING":
        raise_error(ERR_INVALID_STATE, "Order must be PREPARING to mark ready")

    has_accepted_rider = any(
        a["order_id"] == order_id and a["status"] in ("ACCEPTED", "PICKED_UP")
        for a in store.assignments.values()
    )
    if not has_accepted_rider:
        raise_error(ERR_INVALID_STATE, "A rider must have accepted the dispatch before marking ready")

    order["status"] = "READY_FOR_PICKUP"
    touch(order)
    return success_response(serialize(order))


@bp.route("/api/orders/<order_id>/dispatch", methods=["POST"])
def dispatch_order_endpoint(order_id):
    check_role_permission({"PlatformAdmin", "CustomerService"})
    order = store.orders.get(order_id)
    if not order:
        raise_error(ERR_NOT_FOUND, "Order not found")

    from services.dispatch import dispatch_order
    assignment = dispatch_order(order)
    return success_response(serialize(assignment), 201)


@bp.route("/api/orders/<order_id>/returns", methods=["POST"])
def create_return(order_id):
    check_role_permission({"Customer"})
    order = store.orders.get(order_id)
    if not order:
        raise_error(ERR_NOT_FOUND, "Order not found")

    if request.user_id != order["customer_id"]:
        raise_error(ERR_FORBIDDEN, "Cannot create return for another customer's order")

    if order["status"] != "DELIVERED":
        raise_error(ERR_INVALID_STATE, "Order must be DELIVERED to create a return")

    for ret in store.returns.values():
        if ret["order_id"] == order_id and ret["status"] in ("REQUESTED", "APPROVED", "ESCALATED"):
            from errors import ERR_DUPLICATE_RETURN
            raise_error(ERR_DUPLICATE_RETURN, "A return already exists for this order")

    from clock import now as clock_now
    current_time = clock_now()
    if order.get("_actual_delivery_dt"):
        diff = (current_time - order["_actual_delivery_dt"]).total_seconds()
        if diff > 86400:
            from errors import ERR_RETURN_WINDOW_EXPIRED
            raise_error(ERR_RETURN_WINDOW_EXPIRED, "Return window of 24 hours has expired")

    data = request.get_json(force=True, silent=True) or {}

    requested_refund_cents = data.get("requested_refund_cents")
    if requested_refund_cents is None or not isinstance(requested_refund_cents, int):
        from errors import ERR_REFUND_AMOUNT_INVALID
        raise_error(ERR_REFUND_AMOUNT_INVALID, "requested_refund_cents is required and must be an integer")
    from errors import ERR_REFUND_AMOUNT_INVALID
    if requested_refund_cents < 1 or requested_refund_cents > order["subtotal_cents"]:
        raise_error(ERR_REFUND_AMOUNT_INVALID, "requested_refund_cents must be between 1 and subtotal_cents")

    reason = data.get("reason")
    valid_reasons = {"QUALITY_ISSUE", "WRONG_ITEM", "LATE", "OTHER"}
    if reason not in valid_reasons:
        raise_error(ERR_VALIDATION, "reason must be one of QUALITY_ISSUE, WRONG_ITEM, LATE, OTHER")

    from models import make_versioned as mv
    ret = mv({
        "order_id": order_id,
        "reason": reason,
        "requested_refund_cents": requested_refund_cents,
        "approved_refund_cents": None,
        "reviewer_cs_user_id": None,
        "status": "REQUESTED",
    })
    store.returns[ret["id"]] = ret

    order["status"] = "REFUND_REQUESTED"
    touch(order)

    return success_response(serialize(ret), 201)
