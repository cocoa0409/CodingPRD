"""Delivery cascade and assignment-cancel-after-accept logic."""
from __future__ import annotations

from ..bonus import recompute_rider_metrics
from ..fees import (
    commission_cents,
    late_fine_cents,
    minutes_late,
    solo_delivery_fee_cents,
    final_delivery_fee_for_assignment,
)
from ..ids import new_uuid


# ---------- deliver --------------------------------------------------------


def deliver_assignment(store, assignment: dict, order: dict) -> None:
    """Run the full §3.7 delivery cascade. All mutations happen atomically."""
    now_iso = store.now_iso()

    # 1. mark delivery times and compute lateness
    actual = now_iso
    order["actual_delivery_time"] = actual
    mins_late = minutes_late(actual, order["promised_delivery_time"])
    order["minutes_late"] = mins_late

    # 2. final delivery fee (solo + optional merge discount)
    solo_fee = solo_delivery_fee_cents(order["distance_km"], order["is_peak"])
    group_size = _group_size_or_zero(store, assignment)
    final_fee, _discount = final_delivery_fee_for_assignment(solo_fee, group_size)
    order["final_delivery_fee_cents"] = final_fee
    assignment["final_delivery_fee_cents"] = final_fee

    # 3. final commission with possible override
    restaurant = store.restaurants[order["restaurant_id"]]
    rate_override = restaurant.get("commission_rate_override")
    final_comm = commission_cents(order["subtotal_cents"], rate_override)
    order["final_commission_cents"] = final_comm

    # 4. payment_status -> CAPTURED unconditionally
    order["payment_status"] = "CAPTURED"

    # 5. late fine
    rider = store.riders[assignment["rider_id"]]
    if mins_late > 0:
        fine_amount = late_fine_cents(mins_late, final_fee)
        _create_fine(
            store,
            subject_type="RIDER",
            subject_id=rider["id"],
            reason="LATE_DELIVERY",
            amount_cents=fine_amount,
            order_id=order["id"],
        )
        rider["wallet_balance_cents"] -= fine_amount

    # 6. restaurant settlement increment
    restaurant["pending_settlement_cents"] += order["subtotal_cents"] - final_comm
    restaurant["version"] += 1
    restaurant["updated_at"] = now_iso

    # 7. rider wallet credit + status updates
    rider["wallet_balance_cents"] += final_fee
    rider["_completed_count"] += 1
    rider["_on_time_history"].append(mins_late == 0)
    # PRD §3.3: rating is the mean of customer ratings on last 30 completed
    # deliveries on a 0-to-5 scale. The PRD does not specify when customer
    # ratings are submitted (no rating endpoint is defined). We treat each
    # delivery as bringing a default 5.0 rating into the rider's history; this
    # produces a well-defined value for the bonus_tier formula and matches the
    # "initialized at 5.0" expectation for new riders. Future rating endpoints
    # would append to the same history.
    rider["_rating_history"].append(5.0)
    # Assignment transition
    assignment["status"] = "DELIVERED"
    assignment["delivered_at"] = now_iso
    order["status"] = "DELIVERED"
    order["version"] += 1
    order["updated_at"] = now_iso

    # 8. route group lifecycle
    gid = assignment.get("route_group_id")
    if gid:
        grp = store.route_groups.get(gid)
        if grp:
            all_done = all(
                store.assignments[other_id]["status"] == "DELIVERED"
                for other_id in grp["assignment_ids"]
            )
            if all_done:
                grp["status"] = "COMPLETED"

    # 9. rider may return to AVAILABLE when no active assignments remain
    if not _rider_has_active_assignments(store, rider["id"]):
        if rider["status"] == "ON_DELIVERY":
            rider["status"] = "AVAILABLE"

    # 10. recompute bonus tier (uses updated on_time / acceptance / rating)
    recompute_rider_metrics(rider)
    rider["version"] += 1
    rider["updated_at"] = now_iso


# ---------- cancel after accept -------------------------------------------


def cancel_after_accept(store, assignment: dict, order: dict) -> None:
    """Rider abandons an ACCEPTED assignment. Creates a RIDER_NO_SHOW fine of 500c,
    debits the rider's wallet, recomputes bonus tier, then redispatches the order.
    """
    now_iso = store.now_iso()
    assignment["status"] = "CANCELLED"
    rider = store.riders[assignment["rider_id"]]
    _create_fine(
        store,
        subject_type="RIDER",
        subject_id=rider["id"],
        reason="RIDER_NO_SHOW",
        amount_cents=500,
        order_id=order["id"],
    )
    rider["wallet_balance_cents"] -= 500
    # If the assignment belonged to a group, the group may collapse to a solo if
    # this was one of its peers. We mark the group ABANDONED only when no
    # peers remain in an active state.
    gid = assignment.get("route_group_id")
    if gid:
        grp = store.route_groups.get(gid)
        if grp:
            # Remove this assignment from the group.
            if assignment["id"] in grp["assignment_ids"]:
                grp["assignment_ids"].remove(assignment["id"])
            if not grp["assignment_ids"]:
                grp["status"] = "ABANDONED"
            elif len(grp["assignment_ids"]) == 1:
                # The remaining peer is now solo; null out its group reference.
                remaining = store.assignments.get(grp["assignment_ids"][0])
                if remaining:
                    remaining["route_group_id"] = None
                grp["status"] = "ABANDONED"
    # Rider's status: if no active assignments remain, return to AVAILABLE.
    if not _rider_has_active_assignments(store, rider["id"]):
        if rider["status"] == "ON_DELIVERY":
            rider["status"] = "AVAILABLE"
    recompute_rider_metrics(rider)
    rider["version"] += 1
    rider["updated_at"] = now_iso
    # Redispatch a fresh assignment to the next rider.
    if order["status"] in ("RESTAURANT_ACCEPTED", "PREPARING", "READY_FOR_PICKUP"):
        from .dispatch import dispatch_for_order

        dispatch_for_order(store, order)


# ---------- helpers --------------------------------------------------------


def _group_size_or_zero(store, assignment: dict) -> int:
    gid = assignment.get("route_group_id")
    if not gid:
        return 0
    grp = store.route_groups.get(gid)
    if not grp:
        return 0
    return len(grp["assignment_ids"])


def _rider_has_active_assignments(store, rider_id: str) -> bool:
    for a in store.assignments.values():
        if a["rider_id"] == rider_id and a["status"] in (
            "OFFERED",
            "ACCEPTED",
            "PICKED_UP",
        ):
            return True
    return False


def _create_fine(
    store,
    *,
    subject_type: str,
    subject_id: str,
    reason: str,
    amount_cents: int,
    order_id: str | None,
) -> dict:
    fid = new_uuid()
    now_iso = store.now_iso()
    f = {
        "id": fid,
        "subject_type": subject_type,
        "subject_id": subject_id,
        "reason": reason,
        "amount_cents": amount_cents,
        "settlement_status": "PENDING",
        "order_id": order_id,
        "created_at": now_iso,
    }
    store.fines[fid] = f
    return f
