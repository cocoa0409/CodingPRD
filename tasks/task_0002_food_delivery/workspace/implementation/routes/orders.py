"""Order routes: CRUD, state transitions, fee calculations."""

import math
from flask import Blueprint, request as req
import db
from errors import raise_error, ERR_ORDER_NOT_FOUND, ERR_RESTAURANT_NOT_FOUND, \
    ERR_RESTAURANT_NOT_ACTIVE, ERR_RESTAURANT_NOT_ACCEPTING, ERR_CUSTOMER_NOT_FOUND, \
    ERR_CUSTOMER_NOT_ACTIVE, ERR_EMPTY_ORDER, ERR_TOO_MANY_ITEMS, ERR_INVALID_QUANTITY, \
    ERR_MENU_ITEM_NOT_FOUND, ERR_ITEM_NOT_AVAILABLE, ERR_CROSS_RESTAURANT_ORDER, \
    ERR_INVALID_TIP, ERR_PROMOTION_NOT_FOUND, ERR_PROMOTION_NOT_VALID, \
    ERR_BELOW_MINIMUM_ORDER, ERR_INSUFFICIENT_LOYALTY_POINTS, ERR_INVALID_STATE, \
    ERR_INSUFFICIENT_BALANCE, ERR_CANCELLATION_TOO_LATE, ERR_VERSION_CONFLICT
from middleware import require_roles, get_auth
from response import success_response, list_response
from services.calculations import (
    calc_delivery_fee_provisional, calc_service_fee, calc_small_order_fee,
    calc_commission_and_payouts, create_wallet_transaction, add_penalty,
    recalculate_cancellation_rate, haversine_km, calc_estimated_delivery_time,
)

bp = Blueprint("orders", __name__)


def _get_order_or_404(oid):
    o = db.orders.get(oid)
    if not o:
        raise_error(ERR_ORDER_NOT_FOUND, "The referenced order does not exist.")
    return o


def _paginate(request):
    limit = request.args.get("limit", 20, type=int)
    offset = request.args.get("offset", 0, type=int)
    limit = max(1, min(limit, 100))
    offset = max(0, offset)
    return limit, offset


def _order_with_items(order):
    """Return order dict with items included."""
    items = sorted(
        [oi for oi in db.order_items.values() if oi["order_id"] == order["id"]],
        key=lambda x: x["created_at"],
    )
    result = dict(order)
    result["items"] = items
    return result


# ---- Create Order ----

@bp.route("/platform/orders", methods=["POST"])
def create_order():
    require_roles("customer")
    body = req.get_json(force=True, silent=True) or {}

    # Validate restaurant
    restaurant_id = body.get("restaurant_id")
    restaurant = db.restaurants.get(restaurant_id)
    if not restaurant:
        raise_error(ERR_RESTAURANT_NOT_FOUND, "The referenced restaurant does not exist.")
    if restaurant["status"] != "ACTIVE":
        raise_error(ERR_RESTAURANT_NOT_ACTIVE, "Restaurant must be ACTIVE.")
    if not restaurant["is_accepting_orders"]:
        raise_error(ERR_RESTAURANT_NOT_ACCEPTING, "Restaurant is not currently accepting orders.")

    # Validate customer
    customer_id = body.get("customer_id")
    customer = db.customers.get(customer_id)
    if not customer:
        raise_error(ERR_CUSTOMER_NOT_FOUND, "The referenced customer does not exist.")
    if customer["status"] != "ACTIVE":
        raise_error(ERR_CUSTOMER_NOT_ACTIVE, "Customer must be ACTIVE.")

    # Validate items
    items = body.get("items", [])
    if not items:
        raise_error(ERR_EMPTY_ORDER, "Order must contain at least one item.")
    if len(items) > 20:
        raise_error(ERR_TOO_MANY_ITEMS, "Order cannot have more than 20 distinct items.")
    for it in items:
        if it.get("quantity", 0) < 1:
            raise_error(ERR_INVALID_QUANTITY, "Order item quantity must be >= 1.")

    # Validate each menu item
    resolved_items = []
    for it in items:
        mi = db.menu_items.get(it["menu_item_id"])
        if not mi:
            raise_error(ERR_MENU_ITEM_NOT_FOUND, "Menu item not found.")
        if mi["restaurant_id"] != restaurant_id:
            raise_error(ERR_CROSS_RESTAURANT_ORDER, "All items must belong to the same restaurant.")
        if not mi["is_available"]:
            raise_error(ERR_ITEM_NOT_AVAILABLE, "Menu item is not currently available.")
        resolved_items.append((mi, it["quantity"], it.get("special_requests")))

    # Validate tip
    tip_cents = body.get("tip_cents", 0)
    if tip_cents < 0:
        raise_error(ERR_INVALID_TIP, "Tip must be non-negative.")

    # Compute subtotal
    subtotal_cents = 0
    max_prep = 0
    for mi, qty, _ in resolved_items:
        subtotal_cents += mi["base_price_cents"] * qty
        if mi["prep_time_minutes"] > max_prep:
            max_prep = mi["prep_time_minutes"]

    # Delivery fee (provisional)
    delivery_lat = body.get("delivery_latitude")
    delivery_lon = body.get("delivery_longitude")
    delivery_fee_cents, _ = calc_delivery_fee_provisional(restaurant, delivery_lat, delivery_lon)

    # Service fee
    service_fee_cents = calc_service_fee(subtotal_cents)

    # Small order fee
    small_order_fee_cents = calc_small_order_fee(subtotal_cents)

    # Promotion discount
    discount_cents = 0
    promotion_id = body.get("promotion_id")
    if promotion_id:
        promo = db.promotions.get(promotion_id)
        if not promo:
            raise_error(ERR_PROMOTION_NOT_FOUND, "Promotion does not exist.")
        # Validate promotion
        from datetime import datetime, timezone
        now_dt = datetime.now(timezone.utc)
        valid_from = datetime.fromisoformat(promo["valid_from"].replace("Z", "+00:00"))
        valid_until = datetime.fromisoformat(promo["valid_until"].replace("Z", "+00:00"))
        customer_uses = db.promotion_uses_by_customer.get((promotion_id, customer_id), 0)
        if (promo["status"] != "ACTIVE" or
                now_dt < valid_from or now_dt > valid_until or
                promo["current_uses"] >= promo["max_uses"] or
                customer_uses >= promo.get("max_uses_per_customer", 1)):
            raise_error(ERR_PROMOTION_NOT_VALID, "Promotion is not valid.")
        if promo.get("restaurant_id") and promo["restaurant_id"] != restaurant_id:
            raise_error(ERR_PROMOTION_NOT_VALID, "Promotion is not valid for this restaurant.")
        if subtotal_cents < promo["minimum_order_cents"]:
            raise_error(ERR_BELOW_MINIMUM_ORDER, "Order subtotal does not meet promotion minimum.")

        # Calculate discount
        if promo["discount_type"] == "PERCENTAGE":
            discount_cents = int(math.floor(subtotal_cents * promo["discount_value"] / 100))
            if promo.get("max_discount_cents"):
                discount_cents = min(discount_cents, promo["max_discount_cents"])
        elif promo["discount_type"] == "FIXED_AMOUNT":
            discount_cents = promo["discount_value"]
        elif promo["discount_type"] == "FREE_DELIVERY":
            discount_cents = delivery_fee_cents

        discount_cents = min(discount_cents, subtotal_cents)
        promo["current_uses"] += 1
        db.promotion_uses_by_customer[(promotion_id, customer_id)] = customer_uses + 1
        # check if exhausted
        if promo["current_uses"] >= promo["max_uses"]:
            promo["status"] = "EXHAUSTED"

    # Loyalty points redemption
    loyalty_points_to_redeem = body.get("loyalty_points_to_redeem", 0)
    loyalty_discount_cents = 0
    if loyalty_points_to_redeem:
        if loyalty_points_to_redeem < 500:
            raise_error(ERR_INSUFFICIENT_LOYALTY_POINTS, "Minimum 500 points required for redemption.")
        if loyalty_points_to_redeem > customer["loyalty_points"]:
            raise_error(ERR_INSUFFICIENT_LOYALTY_POINTS, "Insufficient loyalty points.")
        loyalty_discount_cents = loyalty_points_to_redeem  # 100 points = 100 cents
        customer["loyalty_points"] -= loyalty_points_to_redeem
        customer["updated_at"] = db.now_iso()
        customer["version"] += 1

    # Order total
    total_cents = subtotal_cents + delivery_fee_cents + service_fee_cents + small_order_fee_cents - discount_cents - loyalty_discount_cents + tip_cents
    total_cents = max(total_cents, 0)

    # Commission and payouts (provisional)
    commission, restaurant_payout, rider_payout = calc_commission_and_payouts(
        subtotal_cents, restaurant["commission_rate"], delivery_fee_cents, tip_cents
    )

    now = db.now_iso()
    order = {
        "id": db.new_id(),
        "customer_id": customer_id,
        "restaurant_id": restaurant_id,
        "delivery_address": body.get("delivery_address"),
        "delivery_latitude": delivery_lat,
        "delivery_longitude": delivery_lon,
        "status": "PLACED",
        "payment_status": "PENDING",
        "subtotal_cents": subtotal_cents,
        "delivery_fee_cents": delivery_fee_cents,
        "service_fee_cents": service_fee_cents,
        "small_order_fee_cents": small_order_fee_cents,
        "discount_cents": discount_cents + loyalty_discount_cents,
        "tip_cents": tip_cents,
        "total_cents": total_cents,
        "commission_amount_cents": commission,
        "rider_payout_cents": rider_payout,
        "restaurant_payout_cents": restaurant_payout,
        "estimated_prep_time_minutes": max_prep,
        "estimated_delivery_time_minutes": None,
        "placed_at": now,
        "confirmed_at": None,
        "picked_up_at": None,
        "delivered_at": None,
        "cancelled_at": None,
        "promotion_id": promotion_id,
        "special_instructions": body.get("special_instructions"),
        "version": 1,
        "created_at": now,
        "updated_at": now,
    }
    db.orders[order["id"]] = order

    # Create order items
    for mi, qty, special in resolved_items:
        oi = {
            "id": db.new_id(),
            "order_id": order["id"],
            "menu_item_id": mi["id"],
            "quantity": qty,
            "unit_price_cents": mi["base_price_cents"],
            "item_total_cents": mi["base_price_cents"] * qty,
            "special_requests": special,
            "created_at": now,
            "updated_at": now,
        }
        db.order_items[oi["id"]] = oi

    # Create loyalty redemption wallet transaction if applicable
    if loyalty_discount_cents > 0:
        create_wallet_transaction(customer_id, "LOYALTY_REDEMPTION", -loyalty_discount_cents, reference_id=order["id"])

    return success_response(_order_with_items(order), 201)


# ---- List / Get ----

@bp.route("/platform/orders", methods=["GET"])
def list_orders():
    require_roles("customer", "restaurant", "platform_admin", "customer_service")
    limit, offset = _paginate(req)
    items = sorted(db.orders.values(), key=lambda x: x["created_at"])
    cid_f = req.args.get("customer_id")
    rid_f = req.args.get("restaurant_id")
    status_f = req.args.get("status")
    if cid_f:
        items = [i for i in items if i["customer_id"] == cid_f]
    if rid_f:
        items = [i for i in items if i["restaurant_id"] == rid_f]
    if status_f:
        items = [i for i in items if i["status"] == status_f]
    total = len(items)
    page = items[offset:offset + limit]
    return list_response(page, total, limit, offset)


@bp.route("/platform/orders/<order_id>", methods=["GET"])
def get_order(order_id):
    require_roles("customer", "restaurant", "rider", "platform_admin", "customer_service")
    o = _get_order_or_404(order_id)
    return success_response(_order_with_items(o))


# ---- State transitions ----

@bp.route("/platform/orders/<order_id>/confirm", methods=["POST"])
def confirm_order(order_id):
    require_roles("restaurant")
    o = _get_order_or_404(order_id)
    if o["status"] != "PLACED":
        raise_error(ERR_INVALID_STATE, "Order must be in PLACED status to confirm.")
    restaurant = db.restaurants.get(o["restaurant_id"])
    if restaurant["status"] != "ACTIVE":
        raise_error(ERR_RESTAURANT_NOT_ACTIVE, "Restaurant must be ACTIVE.")
    # Check menu items still available
    for oi in db.order_items.values():
        if oi["order_id"] == order_id:
            mi = db.menu_items.get(oi["menu_item_id"])
            if mi and not mi["is_available"]:
                raise_error(ERR_ITEM_NOT_AVAILABLE, "Menu item is no longer available.")

    # Authorize payment - debit wallet
    customer = db.customers[o["customer_id"]]
    if customer["wallet_balance_cents"] < o["total_cents"]:
        raise_error(ERR_INSUFFICIENT_BALANCE, "Insufficient wallet balance.")

    create_wallet_transaction(o["customer_id"], "PAYMENT", -o["total_cents"], reference_id=order_id)

    o["status"] = "CONFIRMED"
    o["payment_status"] = "AUTHORIZED"
    o["confirmed_at"] = db.now_iso()
    # Recompute estimated_prep_time_minutes
    max_prep = 0
    for oi in db.order_items.values():
        if oi["order_id"] == order_id:
            mi = db.menu_items.get(oi["menu_item_id"])
            if mi and mi["prep_time_minutes"] > max_prep:
                max_prep = mi["prep_time_minutes"]
    o["estimated_prep_time_minutes"] = max_prep
    o["updated_at"] = db.now_iso()
    o["version"] += 1
    return success_response(_order_with_items(o))


@bp.route("/platform/orders/<order_id>/start-preparing", methods=["POST"])
def start_preparing(order_id):
    require_roles("restaurant")
    o = _get_order_or_404(order_id)
    if o["status"] != "CONFIRMED":
        raise_error(ERR_INVALID_STATE, "Order must be CONFIRMED to start preparing.")
    o["status"] = "PREPARING"
    o["updated_at"] = db.now_iso()
    o["version"] += 1
    return success_response(_order_with_items(o))


@bp.route("/platform/orders/<order_id>/mark-ready", methods=["POST"])
def mark_ready(order_id):
    require_roles("restaurant")
    o = _get_order_or_404(order_id)
    if o["status"] != "PREPARING":
        raise_error(ERR_INVALID_STATE, "Order must be PREPARING to mark ready.")
    o["status"] = "READY_FOR_PICKUP"
    o["updated_at"] = db.now_iso()
    o["version"] += 1
    return success_response(_order_with_items(o))


@bp.route("/platform/orders/<order_id>/pickup", methods=["POST"])
def pickup_order(order_id):
    user_id, role = require_roles("rider")
    o = _get_order_or_404(order_id)
    if o["status"] != "READY_FOR_PICKUP":
        raise_error(ERR_INVALID_STATE, "Order must be READY_FOR_PICKUP for pickup.")
    # Find active delivery for this order
    delivery = None
    for d in db.deliveries.values():
        if d["order_id"] == order_id and d["status"] not in ("CANCELLED_BY_RIDER", "DELIVERED"):
            delivery = d
            break
    if not delivery:
        raise_error(ERR_INVALID_STATE, "No active delivery found for this order.")
    if delivery["status"] != "AT_RESTAURANT":
        raise_error(ERR_INVALID_STATE, "Delivery must be AT_RESTAURANT for pickup.")

    now = db.now_iso()
    o["status"] = "PICKED_UP"
    o["picked_up_at"] = now
    o["updated_at"] = now
    o["version"] += 1

    delivery["status"] = "PICKED_UP"
    delivery["pickup_at"] = now
    delivery["updated_at"] = now
    delivery["version"] += 1

    # Auto-transition delivery to EN_ROUTE
    delivery["status"] = "EN_ROUTE"
    delivery["updated_at"] = db.now_iso()
    delivery["version"] += 1

    return success_response(_order_with_items(o))


@bp.route("/platform/orders/<order_id>/deliver", methods=["POST"])
def deliver_order(order_id):
    user_id, role = require_roles("rider")
    o = _get_order_or_404(order_id)
    if o["status"] != "PICKED_UP":
        raise_error(ERR_INVALID_STATE, "Order must be PICKED_UP to deliver.")

    # Find active delivery for this order
    delivery = None
    for d in db.deliveries.values():
        if d["order_id"] == order_id and d["status"] not in ("CANCELLED_BY_RIDER", "DELIVERED"):
            delivery = d
            break
    if not delivery:
        raise_error(ERR_INVALID_STATE, "No active delivery found for this order.")
    if delivery["status"] not in ("PICKED_UP", "EN_ROUTE"):
        raise_error(ERR_INVALID_STATE, "Delivery must be PICKED_UP or EN_ROUTE.")

    now = db.now_iso()

    # Recalculate final commission/payouts with actual delivery_fee
    commission, restaurant_payout, rider_payout = calc_commission_and_payouts(
        o["subtotal_cents"], db.restaurants[o["restaurant_id"]]["commission_rate"],
        o["delivery_fee_cents"], o["tip_cents"]
    )
    o["commission_amount_cents"] = commission
    o["restaurant_payout_cents"] = restaurant_payout
    o["rider_payout_cents"] = rider_payout

    o["status"] = "DELIVERED"
    o["delivered_at"] = now
    o["payment_status"] = "CAPTURED"
    o["updated_at"] = now
    o["version"] += 1

    delivery["status"] = "DELIVERED"
    delivery["delivered_at"] = now
    delivery["updated_at"] = now
    delivery["version"] += 1

    # Compute actual delivery time
    if delivery.get("pickup_at"):
        from datetime import datetime, timezone
        pickup_dt = datetime.fromisoformat(delivery["pickup_at"].replace("Z", "+00:00"))
        deliver_dt = datetime.fromisoformat(now.replace("Z", "+00:00"))
        actual_minutes = int((deliver_dt - pickup_dt).total_seconds() / 60)
        delivery["actual_delivery_time_minutes"] = actual_minutes
    else:
        actual_minutes = 0
        delivery["actual_delivery_time_minutes"] = 0

    # Late check
    est = o.get("estimated_delivery_time_minutes")
    if est and actual_minutes > est * 1.5:
        delivery["is_late"] = True
    else:
        delivery["is_late"] = False

    # Rider earnings
    delivery["rider_earnings_cents"] = rider_payout

    rider = db.riders[delivery["rider_id"]]
    rider["active_delivery_count"] = max(0, rider["active_delivery_count"] - 1)
    rider["is_at_capacity"] = rider["active_delivery_count"] >= rider["max_concurrent_deliveries"]
    rider["total_deliveries_completed"] += 1
    rider["earnings_balance_cents"] += rider_payout
    rider["updated_at"] = db.now_iso()
    rider["version"] += 1
    recalculate_cancellation_rate(rider)

    # Restaurant earnings
    restaurant = db.restaurants[o["restaurant_id"]]
    restaurant["balance_pending_cents"] += restaurant_payout
    restaurant["total_orders_completed"] += 1
    restaurant["updated_at"] = db.now_iso()
    restaurant["version"] += 1

    # Customer stats
    customer = db.customers[o["customer_id"]]
    customer["total_orders"] += 1
    loyalty_earned = int(math.floor(o["total_cents"] / 100))
    customer["loyalty_points"] += loyalty_earned
    customer["updated_at"] = db.now_iso()
    customer["version"] += 1

    # Late delivery penalty
    if delivery["is_late"]:
        add_penalty(rider, 10, "LATE_DELIVERY", delivery_id=delivery["id"])

    return success_response(_order_with_items(o))


# ---- Cancellations ----

@bp.route("/platform/orders/<order_id>/cancel", methods=["POST"])
def cancel_order(order_id):
    user_id, role = require_roles("customer")
    o = _get_order_or_404(order_id)

    if o["status"] == "PLACED":
        o["status"] = "CANCELLED_BY_CUSTOMER"
        o["cancelled_at"] = db.now_iso()
        o["updated_at"] = db.now_iso()
        o["version"] += 1
        return success_response(_order_with_items(o))

    if o["status"] == "CONFIRMED":
        # Check if delivery exists
        delivery = None
        for d in db.deliveries.values():
            if d["order_id"] == order_id and d["status"] not in ("CANCELLED_BY_RIDER", "FAILED", "DELIVERED"):
                delivery = d
                break
        if delivery and delivery["status"] != "ASSIGNED":
            raise_error(ERR_CANCELLATION_TOO_LATE, "Cannot cancel order after delivery has started.")
        o["status"] = "CANCELLED_BY_CUSTOMER"
        o["cancelled_at"] = db.now_iso()
        o["payment_status"] = "REFUNDED"
        o["updated_at"] = db.now_iso()
        o["version"] += 1
        # Refund
        create_wallet_transaction(o["customer_id"], "REFUND", o["total_cents"], reference_id=order_id)
        # Cancel delivery if exists
        if delivery:
            delivery["status"] = "CANCELLED_BY_RIDER"
            delivery["updated_at"] = db.now_iso()
            delivery["version"] += 1
            rider = db.riders.get(delivery["rider_id"])
            if rider:
                rider["active_delivery_count"] = max(0, rider["active_delivery_count"] - 1)
                rider["is_at_capacity"] = rider["active_delivery_count"] >= rider["max_concurrent_deliveries"]
                rider["updated_at"] = db.now_iso()
                rider["version"] += 1
        return success_response(_order_with_items(o))

    if o["status"] in ("PREPARING", "READY_FOR_PICKUP", "PICKED_UP"):
        raise_error(ERR_CANCELLATION_TOO_LATE, "Cannot cancel order after PREPARING has started.")

    raise_error(ERR_INVALID_STATE, "Order cannot be cancelled from current status.")


@bp.route("/platform/orders/<order_id>/reject", methods=["POST"])
def reject_order(order_id):
    require_roles("restaurant")
    o = _get_order_or_404(order_id)

    if o["status"] == "PLACED":
        o["status"] = "CANCELLED_BY_RESTAURANT"
        o["cancelled_at"] = db.now_iso()
        o["updated_at"] = db.now_iso()
        o["version"] += 1
        return success_response(_order_with_items(o))

    if o["status"] == "CONFIRMED":
        o["status"] = "CANCELLED_BY_RESTAURANT"
        o["cancelled_at"] = db.now_iso()
        o["payment_status"] = "REFUNDED"
        o["updated_at"] = db.now_iso()
        o["version"] += 1
        create_wallet_transaction(o["customer_id"], "REFUND", o["total_cents"], reference_id=order_id)
        # Cancel delivery if exists
        for d in db.deliveries.values():
            if d["order_id"] == order_id and d["status"] not in ("CANCELLED_BY_RIDER", "FAILED", "DELIVERED"):
                d["status"] = "CANCELLED_BY_RIDER"
                d["updated_at"] = db.now_iso()
                d["version"] += 1
                rider = db.riders.get(d["rider_id"])
                if rider:
                    rider["active_delivery_count"] = max(0, rider["active_delivery_count"] - 1)
                    rider["is_at_capacity"] = rider["active_delivery_count"] >= rider["max_concurrent_deliveries"]
                    rider["updated_at"] = db.now_iso()
                    rider["version"] += 1
        return success_response(_order_with_items(o))

    raise_error(ERR_INVALID_STATE, "Order can only be rejected from PLACED or CONFIRMED.")


@bp.route("/platform/orders/<order_id>/platform-cancel", methods=["POST"])
def platform_cancel_order(order_id):
    require_roles("platform_admin")
    o = _get_order_or_404(order_id)
    if o["status"] != "CONFIRMED":
        raise_error(ERR_INVALID_STATE, "Only CONFIRMED orders can be platform-cancelled.")
    o["status"] = "CANCELLED_BY_PLATFORM"
    o["cancelled_at"] = db.now_iso()
    o["payment_status"] = "REFUNDED"
    o["updated_at"] = db.now_iso()
    o["version"] += 1
    create_wallet_transaction(o["customer_id"], "REFUND", o["total_cents"], reference_id=order_id)
    for d in db.deliveries.values():
        if d["order_id"] == order_id and d["status"] not in ("CANCELLED_BY_RIDER", "FAILED", "DELIVERED"):
            d["status"] = "CANCELLED_BY_RIDER"
            d["updated_at"] = db.now_iso()
            d["version"] += 1
            rider = db.riders.get(d["rider_id"])
            if rider:
                rider["active_delivery_count"] = max(0, rider["active_delivery_count"] - 1)
                rider["is_at_capacity"] = rider["active_delivery_count"] >= rider["max_concurrent_deliveries"]
                rider["updated_at"] = db.now_iso()
                rider["version"] += 1
    return success_response(_order_with_items(o))
