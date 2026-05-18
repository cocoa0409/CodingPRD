from flask import Blueprint, request
from store import store
from models import make_unversioned, touch, serialize
from middleware import check_role_permission
from response import success_response
from clock import now, format_timestamp
from errors import (
    raise_error, ERR_FORBIDDEN, ERR_NOT_FOUND, ERR_INVALID_STATE,
    ERR_ORDER_ALREADY_ASSIGNED,
)
from services.computations import (
    compute_delivery_fee, compute_delivery_fee_with_merge,
    compute_commission, compute_late_fine, recompute_bonus_tier,
)
from services.rider_stats import recompute_acceptance_rate, recompute_on_time_rate
from services.dispatch import dispatch_order, try_route_merge

bp = Blueprint("assignments", __name__)


@bp.route("/api/assignments/<assignment_id>", methods=["GET"])
def get_assignment(assignment_id):
    check_role_permission({"PlatformAdmin", "Rider", "CustomerService"})
    assignment = store.assignments.get(assignment_id)
    if not assignment:
        raise_error(ERR_NOT_FOUND, "Assignment not found")

    if request.user_role == "Rider" and assignment["rider_id"] != request.user_id:
        raise_error(ERR_FORBIDDEN, "Cannot view another rider's assignment")

    return success_response(serialize(assignment))


@bp.route("/api/assignments/<assignment_id>/accept", methods=["POST"])
def accept_assignment(assignment_id):
    check_role_permission({"Rider"})
    assignment = store.assignments.get(assignment_id)
    if not assignment:
        raise_error(ERR_NOT_FOUND, "Assignment not found")

    if assignment["rider_id"] != request.user_id:
        raise_error(ERR_FORBIDDEN, "Cannot accept another rider's assignment")

    if assignment["status"] != "OFFERED":
        raise_error(ERR_INVALID_STATE, "Assignment must be OFFERED to accept")

    rider = store.riders.get(assignment["rider_id"])
    if not rider:
        raise_error(ERR_NOT_FOUND, "Rider not found")

    order = store.orders.get(assignment["order_id"])
    if not order:
        raise_error(ERR_NOT_FOUND, "Order not found")

    if rider["status"] not in ("AVAILABLE", "ON_DELIVERY"):
        raise_error(ERR_INVALID_STATE, "Rider must be AVAILABLE or ON_DELIVERY")

    if order["status"] not in ("RESTAURANT_ACCEPTED", "PREPARING", "READY_FOR_PICKUP"):
        raise_error(ERR_INVALID_STATE, "Order is not in a dispatchable state")

    already_assigned = any(
        a["order_id"] == assignment["order_id"]
        and a["id"] != assignment_id
        and a["status"] in ("OFFERED", "ACCEPTED", "PICKED_UP")
        for a in store.assignments.values()
    )
    if already_assigned:
        raise_error(ERR_ORDER_ALREADY_ASSIGNED, "Order already has an accepted assignment")

    assignment["status"] = "ACCEPTED"
    assignment["accepted_at"] = format_timestamp(now())

    if rider["status"] == "AVAILABLE":
        rider["status"] = "ON_DELIVERY"

    order["rider_id"] = rider["id"]
    touch(order)

    recompute_acceptance_rate(rider)
    recompute_bonus_tier(rider)
    touch(rider)

    try_route_merge(assignment, rider)

    return success_response(serialize(assignment))


@bp.route("/api/assignments/<assignment_id>/reject", methods=["POST"])
def reject_assignment(assignment_id):
    check_role_permission({"Rider"})
    assignment = store.assignments.get(assignment_id)
    if not assignment:
        raise_error(ERR_NOT_FOUND, "Assignment not found")

    if assignment["rider_id"] != request.user_id:
        raise_error(ERR_FORBIDDEN, "Cannot reject another rider's assignment")

    if assignment["status"] != "OFFERED":
        raise_error(ERR_INVALID_STATE, "Assignment must be OFFERED to reject")

    assignment["status"] = "REJECTED"

    rider = store.riders.get(assignment["rider_id"])
    if rider:
        recompute_acceptance_rate(rider)
        recompute_bonus_tier(rider)
        touch(rider)

    order = store.orders.get(assignment["order_id"])
    if order:
        dispatch_order(order)

    return success_response(serialize(assignment))


@bp.route("/api/assignments/<assignment_id>/pickup", methods=["POST"])
def pickup_assignment(assignment_id):
    check_role_permission({"Rider"})
    assignment = store.assignments.get(assignment_id)
    if not assignment:
        raise_error(ERR_NOT_FOUND, "Assignment not found")

    if assignment["rider_id"] != request.user_id:
        raise_error(ERR_FORBIDDEN, "Cannot pick up another rider's assignment")

    if assignment["status"] != "ACCEPTED":
        raise_error(ERR_INVALID_STATE, "Assignment must be ACCEPTED to pick up")

    order = store.orders.get(assignment["order_id"])
    if not order:
        raise_error(ERR_NOT_FOUND, "Order not found")

    if order["status"] != "READY_FOR_PICKUP":
        raise_error(ERR_INVALID_STATE, "Order must be READY_FOR_PICKUP to pick up")

    assignment["status"] = "PICKED_UP"
    assignment["picked_up_at"] = format_timestamp(now())

    order["status"] = "PICKED_UP"
    touch(order)

    return success_response(serialize(assignment))


@bp.route("/api/assignments/<assignment_id>/deliver", methods=["POST"])
def deliver_assignment(assignment_id):
    check_role_permission({"Rider"})
    assignment = store.assignments.get(assignment_id)
    if not assignment:
        raise_error(ERR_NOT_FOUND, "Assignment not found")

    if assignment["rider_id"] != request.user_id:
        raise_error(ERR_FORBIDDEN, "Cannot deliver another rider's assignment")

    if assignment["status"] != "PICKED_UP":
        raise_error(ERR_INVALID_STATE, "Assignment must be PICKED_UP to deliver")

    order = store.orders.get(assignment["order_id"])
    if not order:
        raise_error(ERR_NOT_FOUND, "Order not found")

    if order["status"] != "PICKED_UP":
        raise_error(ERR_INVALID_STATE, "Order must be PICKED_UP to deliver")

    rider = store.riders.get(assignment["rider_id"])
    restaurant = store.restaurants.get(order["restaurant_id"])

    current_time = now()

    # 1. Mark assignment delivered
    assignment["status"] = "DELIVERED"
    assignment["delivered_at"] = format_timestamp(current_time)

    # 2. Compute actual delivery time and minutes late
    order["actual_delivery_time"] = format_timestamp(current_time)
    order["_actual_delivery_dt"] = current_time
    promised_dt = order.get("_promised_dt")
    if promised_dt and current_time > promised_dt:
        diff_seconds = (current_time - promised_dt).total_seconds()
        order["minutes_late"] = int(diff_seconds // 60)
    else:
        order["minutes_late"] = 0

    # 3. Reconcile delivery fee
    solo_fee = compute_delivery_fee(order["distance_km"], order["is_peak"])
    route_group = None
    if assignment.get("route_group_id"):
        route_group = store.route_groups.get(assignment["route_group_id"])
    final_fee = compute_delivery_fee_with_merge(solo_fee, route_group, assignment["id"])
    order["final_delivery_fee_cents"] = final_fee
    assignment["final_delivery_fee_cents"] = final_fee

    # 4. Reconcile commission
    override = restaurant["commission_rate_override"] if restaurant else None
    order["final_commission_cents"] = compute_commission(order["subtotal_cents"], override)

    # 5. Capture payment
    order["payment_status"] = "CAPTURED"
    order["status"] = "DELIVERED"
    touch(order)

    # 6. Late fine (if applicable)
    if order["minutes_late"] and order["minutes_late"] > 0:
        fine_amount = compute_late_fine(order["minutes_late"], final_fee)
        fine = make_unversioned({
            "subject_type": "RIDER",
            "subject_id": rider["id"],
            "reason": "LATE_DELIVERY",
            "amount_cents": fine_amount,
            "settlement_status": "PENDING",
            "order_id": order["id"],
        })
        store.fines[fine["id"]] = fine
        rider["wallet_balance_cents"] -= fine_amount

    # 7. Restaurant settlement
    if restaurant:
        restaurant["pending_settlement_cents"] += order["subtotal_cents"] - order["final_commission_cents"]
        touch(restaurant)

    # 8. Rider delivery fee credit
    if rider:
        rider["wallet_balance_cents"] += final_fee
        recompute_on_time_rate(rider)
        recompute_bonus_tier(rider)

        # Check route group completion
        if route_group:
            all_delivered = all(
                store.assignments.get(aid, {}).get("status") == "DELIVERED"
                for aid in route_group["assignment_ids"]
            )
            if all_delivered:
                route_group["status"] = "COMPLETED"

        # Check if rider should return to AVAILABLE
        has_active_assignments = any(
            a["rider_id"] == rider["id"] and a["status"] in ("OFFERED", "ACCEPTED", "PICKED_UP")
            for a in store.assignments.values()
        )
        if not has_active_assignments and rider["status"] == "ON_DELIVERY":
            rider["status"] = "AVAILABLE"

        touch(rider)

    return success_response(serialize(assignment))


@bp.route("/api/assignments/<assignment_id>/cancel", methods=["POST"])
def cancel_assignment(assignment_id):
    check_role_permission({"Rider"})
    assignment = store.assignments.get(assignment_id)
    if not assignment:
        raise_error(ERR_NOT_FOUND, "Assignment not found")

    if assignment["rider_id"] != request.user_id:
        raise_error(ERR_FORBIDDEN, "Cannot cancel another rider's assignment")

    if assignment["status"] != "ACCEPTED":
        raise_error(ERR_INVALID_STATE, "Assignment must be ACCEPTED to cancel")

    order = store.orders.get(assignment["order_id"])
    if order and order["status"] == "PICKED_UP":
        raise_error(ERR_INVALID_STATE, "Cannot cancel after pickup")

    assignment["status"] = "CANCELLED"

    rider = store.riders.get(assignment["rider_id"])
    if rider:
        fine = make_unversioned({
            "subject_type": "RIDER",
            "subject_id": rider["id"],
            "reason": "RIDER_NO_SHOW",
            "amount_cents": 500,
            "settlement_status": "PENDING",
            "order_id": assignment["order_id"],
        })
        store.fines[fine["id"]] = fine
        rider["wallet_balance_cents"] -= 500
        recompute_bonus_tier(rider)

        has_active = any(
            a["rider_id"] == rider["id"] and a["status"] in ("OFFERED", "ACCEPTED", "PICKED_UP")
            for a in store.assignments.values()
        )
        if not has_active and rider["status"] == "ON_DELIVERY":
            rider["status"] = "AVAILABLE"

        touch(rider)

    if assignment.get("route_group_id"):
        rg = store.route_groups.get(assignment["route_group_id"])
        if rg:
            remaining_active = [
                aid for aid in rg["assignment_ids"]
                if aid != assignment_id and store.assignments.get(aid, {}).get("status") not in ("CANCELLED", "REJECTED", "DELIVERED")
            ]
            if not remaining_active:
                rg["status"] = "ABANDONED"

    if order:
        dispatch_order(order)

    return success_response(serialize(assignment))
