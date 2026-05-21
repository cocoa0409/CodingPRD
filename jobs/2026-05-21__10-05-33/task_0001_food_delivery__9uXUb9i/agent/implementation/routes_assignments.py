"""Assignment lifecycle (PRD §3.6, §3.7)."""
from __future__ import annotations

from datetime import datetime, timezone, timedelta

from flask import Blueprint, g

from auth import require_roles
from envelope import success
from errors import ApiError
from common import haversine_m
from pricing import (
    final_delivery_fee_cents,
    solo_delivery_fee_cents,
    compute_final_commission,
    compute_late_fine_amount,
    compute_bonus_tier,
)
from serializers import serialize_assignment
import store
from store import gen_id, iso_z, lock, now


bp = Blueprint("assignments", __name__, url_prefix="/api/assignments")


PROXIMITY_M = 500.0


def _find_assignment(aid: str) -> dict:
    a = store.assignments.get(aid)
    if not a:
        raise ApiError("ERR_NOT_FOUND", "Assignment not found.")
    return a


def _parse_iso(s: str) -> datetime:
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return datetime.fromisoformat(s)


def _recompute_acceptance_rate(rider: dict) -> None:
    hist = store.rider_history.setdefault(rider["id"], {"deliveries": [], "offers": [], "ratings": []})
    offers = hist["offers"][-30:]
    if not offers:
        rider["acceptance_rate"] = 1.0
    else:
        accepted = sum(1 for o in offers if o["accepted"])
        rider["acceptance_rate"] = max(0.0, min(1.0, accepted / len(offers)))


def _recompute_on_time_rate(rider: dict) -> None:
    hist = store.rider_history.setdefault(rider["id"], {"deliveries": [], "offers": [], "ratings": []})
    deliveries = hist["deliveries"][-30:]
    if len(deliveries) < 10:
        rider["on_time_rate"] = 1.0
    else:
        on_time = sum(1 for d in deliveries if d["on_time"])
        rider["on_time_rate"] = max(0.0, min(1.0, on_time / len(deliveries)))


def _recompute_bonus_tier(rider: dict) -> None:
    rider["bonus_tier"] = compute_bonus_tier(
        rider["on_time_rate"], rider["acceptance_rate"], rider["rating"]
    )


def _rider_has_other_active_assignments(rider_id: str, except_assignment_id: str) -> bool:
    for a in store.assignments.values():
        if a["id"] == except_assignment_id:
            continue
        if a["rider_id"] != rider_id:
            continue
        if a["status"] in ("OFFERED", "ACCEPTED", "PICKED_UP"):
            return True
    return False


def _maybe_redispatch(order: dict) -> None:
    """After a rejection/cancellation that does not advance the assignment lifecycle,
    issue a fresh dispatch offer if the order is still dispatchable.
    """
    if order["status"] not in ("RESTAURANT_ACCEPTED", "PREPARING", "READY_FOR_PICKUP"):
        return
    from dispatch import open_dispatch_offer
    open_dispatch_offer(order, raise_on_empty=False)


@bp.get("/<aid>")
@require_roles("PlatformAdmin", "Rider", "CustomerService")
def read_assignment(aid: str):
    a = _find_assignment(aid)
    if g.role == "Rider" and g.user_id != a["rider_id"]:
        raise ApiError("ERR_FORBIDDEN", "Rider identity mismatch.")
    return success(serialize_assignment(a))


@bp.post("/<aid>/accept")
@require_roles("Rider")
def accept_assignment(aid: str):
    a = _find_assignment(aid)
    if g.user_id != a["rider_id"]:
        raise ApiError("ERR_FORBIDDEN", "Rider identity mismatch.")
    rider = store.riders[a["rider_id"]]
    order = store.orders[a["order_id"]]
    if a["status"] != "OFFERED":
        raise ApiError("ERR_INVALID_STATE", "Assignment is not OFFERED.")
    if rider["status"] not in ("AVAILABLE", "ON_DELIVERY"):
        raise ApiError("ERR_INVALID_STATE", "Rider status does not permit acceptance.")
    if order["status"] not in ("RESTAURANT_ACCEPTED", "PREPARING", "READY_FOR_PICKUP"):
        raise ApiError("ERR_INVALID_STATE", "Order is not in a state that permits acceptance.")

    # Uniqueness: no other live assignment for this order
    for other in store.assignments.values():
        if other["id"] == a["id"]:
            continue
        if other["order_id"] == a["order_id"] and other["status"] in ("OFFERED", "ACCEPTED", "PICKED_UP"):
            raise ApiError("ERR_ORDER_ALREADY_ASSIGNED", "Order is already assigned to another rider.")

    with lock():
        t = now()
        a["status"] = "ACCEPTED"
        a["accepted_at"] = iso_z(t)

        was_available = rider["status"] == "AVAILABLE"
        if was_available:
            rider["status"] = "ON_DELIVERY"

        # Record offer outcome (accepted)
        hist = store.rider_history.setdefault(rider["id"], {"deliveries": [], "offers": [], "ratings": []})
        hist["offers"].append({"accepted": True, "assignment_id": a["id"]})
        _recompute_acceptance_rate(rider)
        _recompute_bonus_tier(rider)
        rider["updated_at"] = iso_z(t)
        rider["version"] += 1

        # Route-merge evaluation
        rest = store.restaurants[order["restaurant_id"]]
        merge_target = None
        for grp in store.route_groups.values():
            if grp["rider_id"] != rider["id"] or grp["status"] != "ACTIVE":
                continue
            for peer_aid in grp["assignment_ids"]:
                peer = store.assignments.get(peer_aid)
                if not peer or peer["status"] not in ("OFFERED", "ACCEPTED"):
                    continue
                peer_order = store.orders.get(peer["order_id"])
                if not peer_order:
                    continue
                peer_rest = store.restaurants.get(peer_order["restaurant_id"])
                if not peer_rest:
                    continue
                d = haversine_m(peer_rest["lat"], peer_rest["lng"], rest["lat"], rest["lng"])
                if d <= PROXIMITY_M:
                    merge_target = grp
                    break
            if merge_target:
                break
        if merge_target:
            a["route_group_id"] = merge_target["id"]
            merge_target["assignment_ids"].append(a["id"])

    return success(serialize_assignment(a))


@bp.post("/<aid>/reject")
@require_roles("Rider")
def reject_assignment(aid: str):
    a = _find_assignment(aid)
    if g.user_id != a["rider_id"]:
        raise ApiError("ERR_FORBIDDEN", "Rider identity mismatch.")
    if a["status"] != "OFFERED":
        raise ApiError("ERR_INVALID_STATE", "Only OFFERED assignments can be rejected.")
    rider = store.riders[a["rider_id"]]
    order = store.orders[a["order_id"]]
    with lock():
        a["status"] = "REJECTED"
        hist = store.rider_history.setdefault(rider["id"], {"deliveries": [], "offers": [], "ratings": []})
        hist["offers"].append({"accepted": False, "assignment_id": a["id"]})
        _recompute_acceptance_rate(rider)
        _recompute_bonus_tier(rider)
        rider["updated_at"] = iso_z(now())
        rider["version"] += 1
        _maybe_redispatch(order)
    return success(serialize_assignment(a))


@bp.post("/<aid>/pickup")
@require_roles("Rider")
def pickup_assignment(aid: str):
    a = _find_assignment(aid)
    if g.user_id != a["rider_id"]:
        raise ApiError("ERR_FORBIDDEN", "Rider identity mismatch.")
    order = store.orders[a["order_id"]]
    if a["status"] != "ACCEPTED":
        raise ApiError("ERR_INVALID_STATE", "Only ACCEPTED assignments can be picked up.")
    if order["status"] != "READY_FOR_PICKUP":
        raise ApiError("ERR_INVALID_STATE", "Order is not READY_FOR_PICKUP.")
    with lock():
        t = now()
        a["status"] = "PICKED_UP"
        a["picked_up_at"] = iso_z(t)
        order["status"] = "PICKED_UP"
        order["updated_at"] = iso_z(t)
        order["version"] += 1
    return success(serialize_assignment(a))


@bp.post("/<aid>/cancel")
@require_roles("Rider")
def cancel_assignment(aid: str):
    a = _find_assignment(aid)
    if g.user_id != a["rider_id"]:
        raise ApiError("ERR_FORBIDDEN", "Rider identity mismatch.")
    order = store.orders[a["order_id"]]
    if a["status"] != "ACCEPTED":
        raise ApiError("ERR_INVALID_STATE", "Only ACCEPTED assignments can be cancelled by the rider.")
    if order["status"] in ("PICKED_UP", "DELIVERED"):
        raise ApiError("ERR_INVALID_STATE", "Order has already moved past pickup.")
    rider = store.riders[a["rider_id"]]
    with lock():
        t = now()
        a["status"] = "CANCELLED"
        # Create a RIDER_NO_SHOW fine (flat 500), debit wallet, recompute tier.
        fine_id = gen_id()
        fine = {
            "id": fine_id,
            "subject_type": "RIDER",
            "subject_id": rider["id"],
            "reason": "RIDER_NO_SHOW",
            "amount_cents": 500,
            "settlement_status": "PENDING",
            "order_id": order["id"],
            "created_at": iso_z(t),
        }
        store.fines[fine_id] = fine
        rider["wallet_balance_cents"] -= 500
        _recompute_bonus_tier(rider)
        # Rider returns to AVAILABLE if no other active assignments
        if not _rider_has_other_active_assignments(rider["id"], a["id"]):
            if rider["status"] == "ON_DELIVERY":
                rider["status"] = "AVAILABLE"
        rider["updated_at"] = iso_z(t)
        rider["version"] += 1

        # If this assignment belonged to a route group, the group stays active
        # while peer legs remain; otherwise mark it ABANDONED if everything is
        # cancelled/rejected. Simpler model: do nothing — group is closed at
        # delivery time when all peers are delivered.

        _maybe_redispatch(order)
    return success(serialize_assignment(a))


@bp.post("/<aid>/deliver")
@require_roles("Rider")
def deliver_assignment(aid: str):
    a = _find_assignment(aid)
    if g.user_id != a["rider_id"]:
        raise ApiError("ERR_FORBIDDEN", "Rider identity mismatch.")
    order = store.orders[a["order_id"]]
    rider = store.riders[a["rider_id"]]
    rest = store.restaurants[order["restaurant_id"]]

    if a["status"] != "PICKED_UP":
        raise ApiError("ERR_INVALID_STATE", "Only PICKED_UP assignments can be delivered.")
    if order["status"] != "PICKED_UP":
        raise ApiError("ERR_INVALID_STATE", "Order is not PICKED_UP.")

    with lock():
        t = now()
        # 1. Mark assignment delivered.
        a["status"] = "DELIVERED"
        a["delivered_at"] = iso_z(t)

        # 2. Set actual_delivery_time, minutes_late.
        promised_dt = _parse_iso(order["promised_delivery_time"])
        actual_dt = t
        order["actual_delivery_time"] = iso_z(actual_dt)
        delta = (actual_dt - promised_dt).total_seconds()
        if delta <= 0:
            minutes_late = 0
        else:
            minutes_late = int(delta // 60)
        order["minutes_late"] = minutes_late

        # 3. Compute final delivery fee. Merged iff route_group_id set & >=2 assignments.
        merged = False
        rg = None
        if a.get("route_group_id"):
            rg = store.route_groups[a["route_group_id"]]
            if len(rg["assignment_ids"]) >= 2:
                merged = True
        final_fee = final_delivery_fee_cents(order["distance_km"], order["is_peak"], merged)
        order["final_delivery_fee_cents"] = final_fee
        a["final_delivery_fee_cents"] = final_fee

        # 4. Final commission (override or tiered).
        final_comm = compute_final_commission(order["subtotal_cents"], rest["commission_rate_override"])
        order["final_commission_cents"] = final_comm

        # 5. Order moves to DELIVERED, payment_status -> CAPTURED.
        order["status"] = "DELIVERED"
        order["payment_status"] = "CAPTURED"
        order["updated_at"] = iso_z(t)
        order["version"] += 1

        # 6. Restaurant settlement increment.
        rest["pending_settlement_cents"] += order["subtotal_cents"] - final_comm
        rest["updated_at"] = iso_z(t)
        rest["version"] += 1

        # 7. Rider wallet credit + history + fine for lateness + tier recompute.
        rider["wallet_balance_cents"] += final_fee
        hist = store.rider_history.setdefault(rider["id"], {"deliveries": [], "offers": [], "ratings": []})
        hist["deliveries"].append({"on_time": minutes_late == 0, "assignment_id": a["id"]})
        _recompute_on_time_rate(rider)

        if minutes_late > 0:
            fine_amount = compute_late_fine_amount(minutes_late, final_fee)
            fine_id = gen_id()
            store.fines[fine_id] = {
                "id": fine_id,
                "subject_type": "RIDER",
                "subject_id": rider["id"],
                "reason": "LATE_DELIVERY",
                "amount_cents": fine_amount,
                "settlement_status": "PENDING",
                "order_id": order["id"],
                "created_at": iso_z(t),
            }
            rider["wallet_balance_cents"] -= fine_amount

        _recompute_bonus_tier(rider)

        # 8. Route group completion + rider status.
        if rg is not None:
            all_delivered = all(
                store.assignments[aid_]["status"] == "DELIVERED" for aid_ in rg["assignment_ids"]
            )
            if all_delivered:
                rg["status"] = "COMPLETED"

        if not _rider_has_other_active_assignments(rider["id"], a["id"]):
            rider["status"] = "AVAILABLE"
        rider["updated_at"] = iso_z(t)
        rider["version"] += 1

    return success(serialize_assignment(a))
