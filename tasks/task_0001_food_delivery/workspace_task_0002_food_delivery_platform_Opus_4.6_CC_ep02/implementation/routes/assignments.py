import math
from flask import Blueprint, request
from auth import require_roles, check_ownership
from errors import APIError
from models import (assignments, orders, riders, restaurants, route_groups, fines,
                    operational_resource_base, touch)
from response_envelope import success_response
from calculations import (compute_final_delivery_fee, compute_tiered_commission,
                          compute_flat_commission, compute_late_fine,
                          recompute_rider_bonus)
from routes.orders import create_dispatch_assignment
import clock

bp = Blueprint("assignments", __name__)


def assignment_dict(a):
    return {
        "id": a["id"],
        "order_id": a["order_id"],
        "rider_id": a["rider_id"],
        "route_group_id": a["route_group_id"],
        "status": a["status"],
        "offered_at": a["offered_at"],
        "accepted_at": a["accepted_at"],
        "picked_up_at": a["picked_up_at"],
        "delivered_at": a["delivered_at"],
        "final_delivery_fee_cents": a["final_delivery_fee_cents"],
        "created_at": a["created_at"],
    }


def recompute_acceptance_rate(rider_id):
    rider = riders[rider_id]
    relevant = []
    for a in sorted(assignments.values(), key=lambda x: x["created_at"], reverse=True):
        if a["rider_id"] == rider_id and a["status"] in ("ACCEPTED", "PICKED_UP", "DELIVERED", "REJECTED"):
            relevant.append(a)
            if len(relevant) >= 30:
                break

    if not relevant:
        rider["acceptance_rate"] = 1.0
        return

    accepted = sum(1 for a in relevant if a["status"] in ("ACCEPTED", "PICKED_UP", "DELIVERED"))
    rider["acceptance_rate"] = round(accepted / len(relevant), 10)


def recompute_on_time_rate(rider_id):
    rider = riders[rider_id]
    delivered = []
    for a in sorted(assignments.values(), key=lambda x: x["created_at"], reverse=True):
        if a["rider_id"] == rider_id and a["status"] == "DELIVERED":
            delivered.append(a)
            if len(delivered) >= 30:
                break

    if len(delivered) < 10:
        rider["on_time_rate"] = 1.0
        return

    on_time = 0
    for a in delivered:
        order = orders.get(a["order_id"])
        if order and (order["minutes_late"] is None or order["minutes_late"] == 0):
            on_time += 1

    rider["on_time_rate"] = round(on_time / len(delivered), 10)


def try_route_merge(rider_id, new_assignment, new_order):
    peer_assignments = [
        a for a in assignments.values()
        if a["rider_id"] == rider_id
        and a["id"] != new_assignment["id"]
        and a["status"] == "ACCEPTED"
    ]

    new_restaurant = restaurants.get(new_order["restaurant_id"])
    if not new_restaurant:
        return

    from calculations import haversine_km

    for existing_a in peer_assignments:
        existing_order = orders.get(existing_a["order_id"])
        if not existing_order:
            continue
        existing_restaurant = restaurants.get(existing_order["restaurant_id"])
        if not existing_restaurant:
            continue

        dist_m = haversine_km(
            new_restaurant["lat"], new_restaurant["lng"],
            existing_restaurant["lat"], existing_restaurant["lng"]
        ) * 1000

        if dist_m <= 500:
            if existing_a.get("route_group_id"):
                rg = route_groups.get(existing_a["route_group_id"])
                if rg and rg["status"] == "ACTIVE":
                    rg["assignment_ids"].append(new_assignment["id"])
                    new_assignment["route_group_id"] = rg["id"]
                    return
            else:
                rg = operational_resource_base()
                rg.update({
                    "rider_id": rider_id,
                    "assignment_ids": [existing_a["id"], new_assignment["id"]],
                    "merged_at": clock.format_timestamp(clock.now()),
                    "status": "ACTIVE",
                })
                route_groups[rg["id"]] = rg
                existing_a["route_group_id"] = rg["id"]
                new_assignment["route_group_id"] = rg["id"]
                return


@bp.route("/api/assignments/<assignment_id>", methods=["GET"])
@require_roles("PlatformAdmin", "Rider", "CustomerService")
def get_assignment(assignment_id):
    a = assignments.get(assignment_id)
    if not a:
        raise APIError("ERR_NOT_FOUND", "Assignment not found")

    check_ownership(a["rider_id"], request.user_id, request.user_role, ["Rider"])

    return success_response(assignment_dict(a))


@bp.route("/api/assignments/<assignment_id>/accept", methods=["POST"])
@require_roles("Rider")
def accept_assignment(assignment_id):
    a = assignments.get(assignment_id)
    if not a:
        raise APIError("ERR_NOT_FOUND", "Assignment not found")

    check_ownership(a["rider_id"], request.user_id, request.user_role, ["Rider"])

    if a["status"] != "OFFERED":
        raise APIError("ERR_INVALID_STATE", "Assignment must be in OFFERED to accept")

    rider = riders.get(a["rider_id"])
    if not rider:
        raise APIError("ERR_NOT_FOUND", "Rider not found")

    order = orders.get(a["order_id"])
    if not order:
        raise APIError("ERR_NOT_FOUND", "Order not found")

    if rider["status"] not in ("AVAILABLE", "ON_DELIVERY"):
        raise APIError("ERR_INVALID_STATE", "Rider must be AVAILABLE or ON_DELIVERY to accept")

    if order["status"] not in ("RESTAURANT_ACCEPTED", "PREPARING", "READY_FOR_PICKUP"):
        raise APIError("ERR_INVALID_STATE", "Order is not in a valid state for assignment acceptance")

    for other_a in assignments.values():
        if (other_a["order_id"] == a["order_id"]
                and other_a["id"] != a["id"]
                and other_a["status"] in ("OFFERED", "ACCEPTED", "PICKED_UP")):
            raise APIError("ERR_ORDER_ALREADY_ASSIGNED",
                            "Another assignment already exists for this order")

    a["status"] = "ACCEPTED"
    a["accepted_at"] = clock.format_timestamp(clock.now())

    if rider["status"] == "AVAILABLE":
        rider["status"] = "ON_DELIVERY"

    recompute_acceptance_rate(rider["id"])
    recompute_rider_bonus(rider)
    touch(rider)

    try_route_merge(rider["id"], a, order)

    return success_response(assignment_dict(a))


@bp.route("/api/assignments/<assignment_id>/reject", methods=["POST"])
@require_roles("Rider")
def reject_assignment(assignment_id):
    a = assignments.get(assignment_id)
    if not a:
        raise APIError("ERR_NOT_FOUND", "Assignment not found")

    check_ownership(a["rider_id"], request.user_id, request.user_role, ["Rider"])

    if a["status"] != "OFFERED":
        raise APIError("ERR_INVALID_STATE", "Assignment must be in OFFERED to reject")

    a["status"] = "REJECTED"
    rider = riders.get(a["rider_id"])
    if rider:
        recompute_acceptance_rate(rider["id"])
        recompute_rider_bonus(rider)
        touch(rider)

    excluded = set()
    for ea in assignments.values():
        if ea["order_id"] == a["order_id"] and ea["status"] in ("REJECTED", "CANCELLED"):
            excluded.add(ea["rider_id"])
    create_dispatch_assignment(a["order_id"], excluded)

    return success_response(assignment_dict(a))


@bp.route("/api/assignments/<assignment_id>/pickup", methods=["POST"])
@require_roles("Rider")
def pickup_assignment(assignment_id):
    a = assignments.get(assignment_id)
    if not a:
        raise APIError("ERR_NOT_FOUND", "Assignment not found")

    check_ownership(a["rider_id"], request.user_id, request.user_role, ["Rider"])

    if a["status"] != "ACCEPTED":
        raise APIError("ERR_INVALID_STATE", "Assignment must be in ACCEPTED to pick up")

    order = orders.get(a["order_id"])
    if not order:
        raise APIError("ERR_NOT_FOUND", "Order not found")

    if order["status"] != "READY_FOR_PICKUP":
        raise APIError("ERR_INVALID_STATE", "Order must be READY_FOR_PICKUP")

    a["status"] = "PICKED_UP"
    a["picked_up_at"] = clock.format_timestamp(clock.now())

    order["status"] = "PICKED_UP"
    touch(order)

    return success_response(assignment_dict(a))


@bp.route("/api/assignments/<assignment_id>/deliver", methods=["POST"])
@require_roles("Rider")
def deliver_assignment(assignment_id):
    a = assignments.get(assignment_id)
    if not a:
        raise APIError("ERR_NOT_FOUND", "Assignment not found")

    check_ownership(a["rider_id"], request.user_id, request.user_role, ["Rider"])

    if a["status"] != "PICKED_UP":
        raise APIError("ERR_INVALID_STATE", "Assignment must be in PICKED_UP to deliver")

    order = orders.get(a["order_id"])
    if not order:
        raise APIError("ERR_NOT_FOUND", "Order not found")

    if order["status"] != "PICKED_UP":
        raise APIError("ERR_INVALID_STATE", "Order must be in PICKED_UP")

    rider = riders.get(a["rider_id"])
    restaurant = restaurants.get(order["restaurant_id"])

    now = clock.now()

    a["status"] = "DELIVERED"
    a["delivered_at"] = clock.format_timestamp(now)

    order["status"] = "DELIVERED"
    order["actual_delivery_time"] = clock.format_timestamp(now)

    from datetime import datetime, timezone
    promised = datetime.fromisoformat(order["promised_delivery_time"].replace("Z", "+00:00"))
    diff_seconds = (now - promised).total_seconds()
    if diff_seconds > 0:
        order["minutes_late"] = int(diff_seconds // 60)
    else:
        order["minutes_late"] = 0

    rg = route_groups.get(a["route_group_id"]) if a.get("route_group_id") else None
    final_fee = compute_final_delivery_fee(order["distance_km"], order["is_peak"], rg, a["id"])
    order["final_delivery_fee_cents"] = final_fee
    a["final_delivery_fee_cents"] = final_fee

    if restaurant and restaurant["commission_rate_override"] is not None:
        order["final_commission_cents"] = compute_flat_commission(
            order["subtotal_cents"], restaurant["commission_rate_override"])
    else:
        order["final_commission_cents"] = compute_tiered_commission(order["subtotal_cents"])

    order["payment_status"] = "CAPTURED"
    touch(order)

    if order["minutes_late"] and order["minutes_late"] > 0:
        fine_amount = compute_late_fine(order["minutes_late"], final_fee)
        fine = operational_resource_base()
        fine.update({
            "subject_type": "RIDER",
            "subject_id": rider["id"],
            "reason": "LATE_DELIVERY",
            "amount_cents": fine_amount,
            "settlement_status": "PENDING",
            "order_id": order["id"],
        })
        fines[fine["id"]] = fine
        rider["wallet_balance_cents"] -= fine_amount
        recompute_on_time_rate(rider["id"])
        recompute_rider_bonus(rider)

    if restaurant:
        restaurant["pending_settlement_cents"] += order["subtotal_cents"] - order["final_commission_cents"]
        touch(restaurant)

    rider["wallet_balance_cents"] += final_fee

    if rg:
        all_delivered = all(
            assignments.get(aid, {}).get("status") == "DELIVERED"
            for aid in rg["assignment_ids"]
        )
        if all_delivered:
            rg["status"] = "COMPLETED"

    has_active = False
    for other_a in assignments.values():
        if (other_a["rider_id"] == rider["id"]
                and other_a["id"] != a["id"]
                and other_a["status"] in ("OFFERED", "ACCEPTED", "PICKED_UP")):
            has_active = True
            break

    if not has_active:
        rider["status"] = "AVAILABLE"

    recompute_on_time_rate(rider["id"])
    recompute_rider_bonus(rider)
    touch(rider)

    return success_response(assignment_dict(a))


@bp.route("/api/assignments/<assignment_id>/cancel", methods=["POST"])
@require_roles("Rider")
def cancel_assignment(assignment_id):
    a = assignments.get(assignment_id)
    if not a:
        raise APIError("ERR_NOT_FOUND", "Assignment not found")

    check_ownership(a["rider_id"], request.user_id, request.user_role, ["Rider"])

    if a["status"] != "ACCEPTED":
        raise APIError("ERR_INVALID_STATE", "Assignment must be in ACCEPTED to cancel")

    order = orders.get(a["order_id"])
    if order and order["status"] == "PICKED_UP":
        raise APIError("ERR_INVALID_STATE", "Cannot cancel after pickup")

    a["status"] = "CANCELLED"

    rider = riders.get(a["rider_id"])
    fine = operational_resource_base()
    fine.update({
        "subject_type": "RIDER",
        "subject_id": rider["id"],
        "reason": "RIDER_NO_SHOW",
        "amount_cents": 500,
        "settlement_status": "PENDING",
        "order_id": a["order_id"],
    })
    fines[fine["id"]] = fine
    rider["wallet_balance_cents"] -= 500
    recompute_rider_bonus(rider)
    touch(rider)

    if a.get("route_group_id"):
        rg = route_groups.get(a["route_group_id"])
        if rg:
            active_in_group = [
                aid for aid in rg["assignment_ids"]
                if aid != a["id"] and assignments.get(aid, {}).get("status") in ("ACCEPTED", "PICKED_UP")
            ]
            if not active_in_group:
                rg["status"] = "ABANDONED"

    excluded = set()
    for ea in assignments.values():
        if ea["order_id"] == a["order_id"] and ea["status"] in ("REJECTED", "CANCELLED"):
            excluded.add(ea["rider_id"])
    create_dispatch_assignment(a["order_id"], excluded)

    return success_response(assignment_dict(a))
