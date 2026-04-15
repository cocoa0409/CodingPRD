"""Delivery routes: assignment, state transitions."""

from flask import Blueprint, request as req
import db
from errors import raise_error, ERR_ORDER_NOT_FOUND, ERR_DELIVERY_NOT_FOUND, \
    ERR_RIDER_NOT_FOUND, ERR_RIDER_NOT_AVAILABLE, ERR_RIDER_AT_CAPACITY, \
    ERR_INVALID_STATE
from middleware import require_roles
from response import success_response
from services.calculations import (
    haversine_km, calc_delivery_fee_final, calc_commission_and_payouts,
    calc_estimated_delivery_time, add_penalty, recalculate_cancellation_rate,
)

bp = Blueprint("deliveries", __name__)


def _get_order_or_404(oid):
    o = db.orders.get(oid)
    if not o:
        raise_error(ERR_ORDER_NOT_FOUND, "The referenced order does not exist.")
    return o


def _get_delivery_or_404(order_id, delivery_id):
    _get_order_or_404(order_id)
    d = db.deliveries.get(delivery_id)
    if not d or d["order_id"] != order_id:
        raise_error(ERR_DELIVERY_NOT_FOUND, "The referenced delivery does not exist.")
    return d


@bp.route("/platform/orders/<order_id>/deliveries", methods=["POST"])
def create_delivery(order_id):
    require_roles("platform_admin")
    order = _get_order_or_404(order_id)
    body = req.get_json(force=True, silent=True) or {}
    rider_id = body.get("rider_id")
    rider = db.riders.get(rider_id)
    if not rider:
        raise_error(ERR_RIDER_NOT_FOUND, "The referenced rider does not exist.")
    if rider["status"] != "ACTIVE" or not rider["is_online"]:
        raise_error(ERR_RIDER_NOT_AVAILABLE, "Rider is not available.")
    if rider["active_delivery_count"] >= rider["max_concurrent_deliveries"]:
        raise_error(ERR_RIDER_AT_CAPACITY, "Rider has reached max concurrent deliveries.")

    restaurant = db.restaurants[order["restaurant_id"]]
    dist_km = haversine_km(
        restaurant["latitude"], restaurant["longitude"],
        order["delivery_latitude"], order["delivery_longitude"],
    )

    # Recalculate delivery fee with vehicle type
    new_fee = calc_delivery_fee_final(
        restaurant, order["delivery_latitude"], order["delivery_longitude"],
        rider["vehicle_type"], dist_km,
    )
    order["delivery_fee_cents"] = new_fee

    # Recalculate total
    order["total_cents"] = (
        order["subtotal_cents"] + new_fee + order["service_fee_cents"]
        + order["small_order_fee_cents"] - order["discount_cents"] + order["tip_cents"]
    )
    order["total_cents"] = max(order["total_cents"], 0)

    # Recalculate payouts
    commission, restaurant_payout, rider_payout = calc_commission_and_payouts(
        order["subtotal_cents"], restaurant["commission_rate"], new_fee, order["tip_cents"]
    )
    order["commission_amount_cents"] = commission
    order["restaurant_payout_cents"] = restaurant_payout
    order["rider_payout_cents"] = rider_payout

    # Estimated delivery time
    est = calc_estimated_delivery_time(dist_km, rider["vehicle_type"], order["estimated_prep_time_minutes"])
    order["estimated_delivery_time_minutes"] = est

    order["updated_at"] = db.now_iso()
    order["version"] += 1

    now = db.now_iso()
    delivery = {
        "id": db.new_id(),
        "order_id": order_id,
        "rider_id": rider_id,
        "status": "ASSIGNED",
        "assigned_at": now,
        "pickup_at": None,
        "delivered_at": None,
        "distance_km": round(dist_km, 2),
        "actual_delivery_time_minutes": None,
        "is_late": False,
        "rider_earnings_cents": 0,
        "version": 1,
        "created_at": now,
        "updated_at": now,
    }
    db.deliveries[delivery["id"]] = delivery

    rider["active_delivery_count"] += 1
    rider["is_at_capacity"] = rider["active_delivery_count"] >= rider["max_concurrent_deliveries"]
    rider["updated_at"] = db.now_iso()
    rider["version"] += 1

    return success_response(delivery, 201)


@bp.route("/platform/orders/<order_id>/deliveries/<delivery_id>", methods=["GET"])
def get_delivery(order_id, delivery_id):
    require_roles("rider", "restaurant", "platform_admin")
    d = _get_delivery_or_404(order_id, delivery_id)
    return success_response(d)


@bp.route("/platform/orders/<order_id>/deliveries/<delivery_id>/start", methods=["POST"])
def start_delivery(order_id, delivery_id):
    user_id, role = require_roles("rider")
    d = _get_delivery_or_404(order_id, delivery_id)
    if d["status"] != "ASSIGNED":
        raise_error(ERR_INVALID_STATE, "Delivery must be ASSIGNED to start.")
    d["status"] = "HEADING_TO_RESTAURANT"
    d["updated_at"] = db.now_iso()
    d["version"] += 1
    return success_response(d)


@bp.route("/platform/orders/<order_id>/deliveries/<delivery_id>/arrive", methods=["POST"])
def arrive_delivery(order_id, delivery_id):
    user_id, role = require_roles("rider")
    d = _get_delivery_or_404(order_id, delivery_id)
    if d["status"] != "HEADING_TO_RESTAURANT":
        raise_error(ERR_INVALID_STATE, "Delivery must be HEADING_TO_RESTAURANT to arrive.")
    d["status"] = "AT_RESTAURANT"
    d["updated_at"] = db.now_iso()
    d["version"] += 1
    return success_response(d)


@bp.route("/platform/orders/<order_id>/deliveries/<delivery_id>/cancel", methods=["POST"])
def cancel_delivery(order_id, delivery_id):
    user_id, role = require_roles("rider")
    d = _get_delivery_or_404(order_id, delivery_id)
    if d["status"] not in ("ASSIGNED", "HEADING_TO_RESTAURANT"):
        raise_error(ERR_INVALID_STATE, "Delivery can only be cancelled from ASSIGNED or HEADING_TO_RESTAURANT.")

    d["status"] = "CANCELLED_BY_RIDER"
    d["updated_at"] = db.now_iso()
    d["version"] += 1

    rider = db.riders[d["rider_id"]]
    rider["active_delivery_count"] = max(0, rider["active_delivery_count"] - 1)
    rider["is_at_capacity"] = rider["active_delivery_count"] >= rider["max_concurrent_deliveries"]
    rider["cancellation_count"] += 1
    recalculate_cancellation_rate(rider)
    add_penalty(rider, 20, "CANCELLATION", delivery_id=delivery_id)

    return success_response(d)
