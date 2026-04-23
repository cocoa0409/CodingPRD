import math
from flask import Blueprint, request
from middleware.auth import require_roles
from storage import db
from models.base import now_ts
from response import success_response
from errors import (raise_error, ERR_NOT_FOUND, ERR_FORBIDDEN, ERR_INVALID_STATE,
                    ERR_ORDER_ALREADY_ASSIGNED)
from services.dispatch import dispatch_order, try_merge_route
from services.delivery_fee import compute_final_delivery_fee
from services.commission import compute_commission
from services.fine_service import create_late_delivery_fine, create_no_show_fine
from services.rider_metrics import (recompute_acceptance_rate, recompute_on_time_rate,
                                     recompute_bonus_tier)

bp = Blueprint("assignments", __name__)


def get_assignment_or_404(assignment_id):
    a = db.assignments.get(assignment_id)
    if not a:
        raise_error(ERR_NOT_FOUND, "Assignment not found.")
    return a


@bp.route("/api/assignments/<assignment_id>", methods=["GET"])
@require_roles("PlatformAdmin", "Rider", "CustomerService")
def get_assignment(assignment_id):
    a = get_assignment_or_404(assignment_id)
    if request.user_role == "Rider" and request.user_id != a.rider_id:
        raise_error(ERR_FORBIDDEN, "Cannot view another rider's assignment.")
    return success_response(a.to_dict())


@bp.route("/api/assignments/<assignment_id>/accept", methods=["POST"])
@require_roles("Rider")
def accept_assignment(assignment_id):
    a = get_assignment_or_404(assignment_id)
    if request.user_id != a.rider_id:
        raise_error(ERR_FORBIDDEN, "Cannot accept another rider's assignment.")

    rider = db.riders.get(a.rider_id)
    if not rider:
        raise_error(ERR_NOT_FOUND, "Rider not found.")

    order = db.orders.get(a.order_id)
    if not order:
        raise_error(ERR_NOT_FOUND, "Order not found.")

    if rider.status not in ("AVAILABLE", "ON_DELIVERY"):
        raise_error(ERR_INVALID_STATE, "Rider must be AVAILABLE or ON_DELIVERY.")

    if order.status not in ("RESTAURANT_ACCEPTED", "PREPARING", "READY_FOR_PICKUP"):
        raise_error(ERR_INVALID_STATE, "Order is not in a dispatchable state.")

    if a.status != "OFFERED":
        raise_error(ERR_INVALID_STATE, "Assignment must be in OFFERED state.")

    already_assigned = any(
        x for x in db.assignments.values()
        if x.order_id == a.order_id and x.id != a.id
        and x.status in ("OFFERED", "ACCEPTED", "PICKED_UP")
    )
    if already_assigned:
        raise_error(ERR_ORDER_ALREADY_ASSIGNED, "Order is already assigned to another rider.")

    a.status = "ACCEPTED"
    a.accepted_at = now_ts()

    if rider.status == "AVAILABLE":
        rider.status = "ON_DELIVERY"

    recompute_acceptance_rate(rider)
    recompute_bonus_tier(rider)
    rider.touch()

    try_merge_route(a, rider)

    return success_response(a.to_dict())


@bp.route("/api/assignments/<assignment_id>/reject", methods=["POST"])
@require_roles("Rider")
def reject_assignment(assignment_id):
    a = get_assignment_or_404(assignment_id)
    if request.user_id != a.rider_id:
        raise_error(ERR_FORBIDDEN, "Cannot reject another rider's assignment.")
    if a.status != "OFFERED":
        raise_error(ERR_INVALID_STATE, "Assignment must be in OFFERED state.")

    a.status = "REJECTED"
    rider = db.riders.get(a.rider_id)
    if rider:
        recompute_acceptance_rate(rider)
        recompute_bonus_tier(rider)
        rider.touch()

    tried = {x.rider_id for x in db.assignments.values() if x.order_id == a.order_id}
    dispatch_order(a.order_id, exclude_rider_ids=tried)

    return success_response(a.to_dict())


@bp.route("/api/assignments/<assignment_id>/pickup", methods=["POST"])
@require_roles("Rider")
def pickup_assignment(assignment_id):
    a = get_assignment_or_404(assignment_id)
    if request.user_id != a.rider_id:
        raise_error(ERR_FORBIDDEN, "Cannot pick up another rider's assignment.")
    if a.status != "ACCEPTED":
        raise_error(ERR_INVALID_STATE, "Assignment must be in ACCEPTED state.")

    order = db.orders.get(a.order_id)
    if not order:
        raise_error(ERR_NOT_FOUND, "Order not found.")
    if order.status != "READY_FOR_PICKUP":
        raise_error(ERR_INVALID_STATE, "Order must be in READY_FOR_PICKUP state.")

    a.status = "PICKED_UP"
    a.picked_up_at = now_ts()
    order.status = "PICKED_UP"
    order.touch()

    return success_response(a.to_dict())


@bp.route("/api/assignments/<assignment_id>/deliver", methods=["POST"])
@require_roles("Rider")
def deliver_assignment(assignment_id):
    a = get_assignment_or_404(assignment_id)
    if request.user_id != a.rider_id:
        raise_error(ERR_FORBIDDEN, "Cannot deliver another rider's assignment.")
    if a.status != "PICKED_UP":
        raise_error(ERR_INVALID_STATE, "Assignment must be in PICKED_UP state.")

    order = db.orders.get(a.order_id)
    if not order:
        raise_error(ERR_NOT_FOUND, "Order not found.")
    if order.status != "PICKED_UP":
        raise_error(ERR_INVALID_STATE, "Order must be in PICKED_UP state.")

    rider = db.riders.get(a.rider_id)
    if not rider:
        raise_error(ERR_NOT_FOUND, "Rider not found.")

    restaurant = db.restaurants.get(order.restaurant_id)

    current_time = now_ts()
    a.status = "DELIVERED"
    a.delivered_at = current_time

    order.status = "DELIVERED"
    order.actual_delivery_time = current_time

    seconds_diff = (current_time - order.promised_delivery_time).total_seconds()
    if seconds_diff > 0:
        order.minutes_late = int(math.floor(seconds_diff / 60))
    else:
        order.minutes_late = 0

    is_merged = False
    if a.route_group_id:
        rg = db.route_groups.get(a.route_group_id)
        if rg and len(rg.assignment_ids) >= 2:
            is_merged = True

    final_fee = compute_final_delivery_fee(order.distance_km, order.is_peak, is_merged)
    order.final_delivery_fee_cents = final_fee
    a.final_delivery_fee_cents = final_fee

    commission_rate = restaurant.commission_rate_override if restaurant else None
    order.final_commission_cents = compute_commission(order.subtotal_cents, commission_rate)

    order.payment_status = "CAPTURED"

    recompute_on_time_rate(rider)

    if order.minutes_late > 0:
        create_late_delivery_fine(rider, order.minutes_late, final_fee)

    if restaurant:
        restaurant.pending_settlement_cents += order.subtotal_cents - order.final_commission_cents
        restaurant.touch()

    rider.wallet_balance_cents += final_fee
    recompute_bonus_tier(rider)
    rider.touch()

    order.touch()

    if a.route_group_id:
        rg = db.route_groups.get(a.route_group_id)
        if rg:
            all_delivered = all(
                db.assignments.get(aid) and db.assignments[aid].status == "DELIVERED"
                for aid in rg.assignment_ids
            )
            if all_delivered:
                rg.status = "COMPLETED"

    remaining_active = any(
        x for x in db.assignments.values()
        if x.rider_id == rider.id and x.status in ("OFFERED", "ACCEPTED", "PICKED_UP")
    )
    if not remaining_active:
        rider.status = "AVAILABLE"
        rider.touch()

    return success_response(a.to_dict())


@bp.route("/api/assignments/<assignment_id>/cancel", methods=["POST"])
@require_roles("Rider")
def cancel_assignment(assignment_id):
    a = get_assignment_or_404(assignment_id)
    if request.user_id != a.rider_id:
        raise_error(ERR_FORBIDDEN, "Cannot cancel another rider's assignment.")
    if a.status != "ACCEPTED":
        raise_error(ERR_INVALID_STATE, "Assignment must be in ACCEPTED state to cancel.")

    order = db.orders.get(a.order_id)
    if order and order.status == "PICKED_UP":
        raise_error(ERR_INVALID_STATE, "Cannot cancel after order has been picked up.")

    a.status = "CANCELLED"

    rider = db.riders.get(a.rider_id)
    if rider:
        create_no_show_fine(rider)
        rider.touch()

    if a.route_group_id:
        rg = db.route_groups.get(a.route_group_id)
        if rg:
            rg.assignment_ids = [aid for aid in rg.assignment_ids if aid != a.id]
            if not rg.assignment_ids:
                rg.status = "ABANDONED"

    tried = {x.rider_id for x in db.assignments.values() if x.order_id == a.order_id}
    dispatch_order(a.order_id, exclude_rider_ids=tried)

    remaining_active = any(
        x for x in db.assignments.values()
        if x.rider_id == rider.id and x.status in ("OFFERED", "ACCEPTED", "PICKED_UP")
    )
    if not remaining_active and rider and rider.status == "ON_DELIVERY":
        rider.status = "AVAILABLE"
        rider.touch()

    return success_response(a.to_dict())
