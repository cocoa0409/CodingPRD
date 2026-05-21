"""Assignment routes — accept, reject, pickup, deliver, cancel."""
from __future__ import annotations

from datetime import timedelta

from flask import Blueprint

from .. import cascade, fees
from ..auth import require_role
from ..bonus import recompute_rider_metrics_on_offer_outcome, recompute_bonus_tier, on_delivery_completed
from ..clock import parse_iso
from ..dispatch import open_dispatch, _has_unpicked_in_range
from ..envelope import envelope_object
from ..errors import ApiError
from ..geo import distance_metres
from ..ids import new_uuid
from ..store import get_clock, get_store

bp = Blueprint("assignments", __name__, url_prefix="/api")


def _ensure_assignment(store, aid):
    rec = store.assignments.get(aid)
    if not rec:
        raise ApiError("ERR_NOT_FOUND", f"Assignment {aid} not found")
    return rec


def _find_merge_peer(store, rider, new_assignment):
    """Return a live peer assignment within 500 m, or None.

    A "peer" is another live (ACCEPTED or PICKED_UP — i.e., unpicked at the
    pickup-restaurant level) assignment owned by the same rider whose
    pickup restaurant lies within 500 m of the new one's pickup.
    """
    new_order = store.orders[new_assignment["order_id"]]
    new_pickup = store.restaurants[new_order["restaurant_id"]]
    for peer in store.assignments.values():
        if peer["id"] == new_assignment["id"]:
            continue
        if peer["rider_id"] != rider["id"]:
            continue
        if peer["status"] not in {"ACCEPTED"}:
            # PICKED_UP no longer counts as a route-merge peer because
            # the rider has already departed the pickup.
            continue
        peer_order = store.orders[peer["order_id"]]
        peer_pickup = store.restaurants[peer_order["restaurant_id"]]
        if distance_metres(
            peer_pickup["lat"], peer_pickup["lng"],
            new_pickup["lat"], new_pickup["lng"],
        ) <= 500.0:
            return peer
    return None


def _attach_to_route_group(store, clock, rider, new_assignment):
    """If a merge peer exists, ensure both share an ACTIVE RouteGroup."""
    peer = _find_merge_peer(store, rider, new_assignment)
    if peer is None:
        return
    if peer.get("route_group_id"):
        group = store.route_groups[peer["route_group_id"]]
        if new_assignment["id"] not in group["assignment_ids"]:
            group["assignment_ids"].append(new_assignment["id"])
        new_assignment["route_group_id"] = group["id"]
        return
    # Create a brand new RouteGroup containing both peer and new assignment.
    gid = new_uuid()
    group = {
        "id": gid,
        "rider_id": rider["id"],
        "assignment_ids": [peer["id"], new_assignment["id"]],
        "merged_at": clock.now_iso(),
        "status": "ACTIVE",
        "created_at": clock.now_iso(),
    }
    store.route_groups[gid] = group
    peer["route_group_id"] = gid
    new_assignment["route_group_id"] = gid


@bp.get("/assignments/<aid>")
def read_assignment(aid):
    uid, role = require_role({"PlatformAdmin", "Rider", "CustomerService"})
    store = get_store()
    with store.lock:
        rec = _ensure_assignment(store, aid)
        if role == "Rider" and uid != rec["rider_id"]:
            raise ApiError("ERR_FORBIDDEN", "not your assignment")
    return envelope_object(rec)


@bp.post("/assignments/<aid>/accept")
def accept_assignment(aid):
    uid, _ = require_role({"Rider"})
    store = get_store()
    clock = get_clock()
    with store.lock:
        a = _ensure_assignment(store, aid)
        if uid != a["rider_id"]:
            raise ApiError("ERR_FORBIDDEN", "not your assignment")
        if a["status"] != "OFFERED":
            raise ApiError("ERR_INVALID_STATE", "assignment not OFFERED")
        order = store.orders[a["order_id"]]
        if order["status"] not in {"RESTAURANT_ACCEPTED", "PREPARING", "READY_FOR_PICKUP"}:
            raise ApiError("ERR_INVALID_STATE", "order not acceptable")
        rider = store.riders[a["rider_id"]]
        if rider["status"] not in {"AVAILABLE", "ON_DELIVERY"}:
            raise ApiError("ERR_INVALID_STATE", "rider not eligible")
        # Uniqueness: no other live assignment for this order
        for other in store.assignments.values():
            if other["id"] == a["id"]:
                continue
            if other["order_id"] == a["order_id"] and other["status"] in {"ACCEPTED", "PICKED_UP"}:
                raise ApiError("ERR_ORDER_ALREADY_ASSIGNED", "order already assigned")

        a["status"] = "ACCEPTED"
        a["accepted_at"] = clock.now_iso()
        # Attempt route-merge attachment first — peer search is based on
        # current accepted assignments owned by this rider.
        _attach_to_route_group(store, clock, rider, a)
        if rider["status"] != "ON_DELIVERY":
            rider["status"] = "ON_DELIVERY"
        cascade.touch(rider, clock)

        # Recompute acceptance_rate
        recompute_rider_metrics_on_offer_outcome(store, rider, accepted=True)
        recompute_bonus_tier(rider)
    return envelope_object(a)


@bp.post("/assignments/<aid>/reject")
def reject_assignment(aid):
    uid, _ = require_role({"Rider"})
    store = get_store()
    clock = get_clock()
    with store.lock:
        a = _ensure_assignment(store, aid)
        if uid != a["rider_id"]:
            raise ApiError("ERR_FORBIDDEN", "not your assignment")
        if a["status"] != "OFFERED":
            raise ApiError("ERR_INVALID_STATE", "assignment not OFFERED")
        a["status"] = "REJECTED"
        rider = store.riders[a["rider_id"]]
        recompute_rider_metrics_on_offer_outcome(store, rider, accepted=False)
        recompute_bonus_tier(rider)
        cascade.touch(rider, clock)
        # Redispatch
        order = store.orders[a["order_id"]]
        if order["status"] in {"RESTAURANT_ACCEPTED", "PREPARING", "READY_FOR_PICKUP"}:
            open_dispatch(store, clock, order, force=True)
    return envelope_object(a)


@bp.post("/assignments/<aid>/pickup")
def pickup_assignment(aid):
    uid, _ = require_role({"Rider"})
    store = get_store()
    clock = get_clock()
    with store.lock:
        a = _ensure_assignment(store, aid)
        if uid != a["rider_id"]:
            raise ApiError("ERR_FORBIDDEN", "not your assignment")
        if a["status"] != "ACCEPTED":
            raise ApiError("ERR_INVALID_STATE", "assignment not ACCEPTED")
        order = store.orders[a["order_id"]]
        if order["status"] != "READY_FOR_PICKUP":
            raise ApiError("ERR_INVALID_STATE", "order not READY_FOR_PICKUP")
        a["status"] = "PICKED_UP"
        a["picked_up_at"] = clock.now_iso()
        order["status"] = "PICKED_UP"
        cascade.touch(order, clock)
    return envelope_object(a)


@bp.post("/assignments/<aid>/deliver")
def deliver_assignment(aid):
    uid, _ = require_role({"Rider"})
    store = get_store()
    clock = get_clock()
    with store.lock:
        a = _ensure_assignment(store, aid)
        if uid != a["rider_id"]:
            raise ApiError("ERR_FORBIDDEN", "not your assignment")
        if a["status"] != "PICKED_UP":
            raise ApiError("ERR_INVALID_STATE", "assignment not PICKED_UP")
        order = store.orders[a["order_id"]]
        if order["status"] != "PICKED_UP":
            raise ApiError("ERR_INVALID_STATE", "order not PICKED_UP")

        # 1. delivered timestamps and minutes_late
        now_dt = clock.now_dt()
        promised = parse_iso(order["promised_delivery_time"])
        seconds_late = (now_dt - promised).total_seconds()
        minutes_late = max(0, int(seconds_late // 60))
        from ..clock import iso
        order["actual_delivery_time"] = iso(now_dt)
        order["minutes_late"] = minutes_late

        # 2. final delivery fee
        solo_fee = fees.delivery_fee(order["distance_km"], order["is_peak"])
        merged_with_peers = False
        if a["route_group_id"]:
            group = store.route_groups[a["route_group_id"]]
            if len(group["assignment_ids"]) >= 2:
                merged_with_peers = True
        if merged_with_peers:
            disc = fees.merge_discount(solo_fee)
            final_fee = solo_fee - disc
        else:
            final_fee = solo_fee
        order["final_delivery_fee_cents"] = final_fee
        a["final_delivery_fee_cents"] = final_fee
        a["status"] = "DELIVERED"
        a["delivered_at"] = order["actual_delivery_time"]

        # 3. final commission
        restaurant = store.restaurants[order["restaurant_id"]]
        if restaurant["commission_rate_override"] is not None:
            final_comm = fees.flat_commission(order["subtotal_cents"], restaurant["commission_rate_override"])
        else:
            final_comm = fees.tiered_commission(order["subtotal_cents"])
        order["final_commission_cents"] = final_comm

        # 4. payment captured
        order["payment_status"] = "CAPTURED"
        order["status"] = "DELIVERED"

        # 6. restaurant settlement increment
        restaurant["pending_settlement_cents"] += order["subtotal_cents"] - final_comm
        cascade.touch(restaurant, clock)

        # Rider credits and metric updates
        rider = store.riders[a["rider_id"]]
        rider["wallet_balance_cents"] += final_fee
        # Recompute on_time_rate over the rider's last 30 completed deliveries
        on_delivery_completed(store, rider, was_on_time=(minutes_late == 0))

        # 5. late fine if any
        fine_obj = None
        if minutes_late > 0:
            amount = fees.late_fine(minutes_late, final_fee)
            fine_obj = {
                "id": new_uuid(),
                "subject_type": "RIDER",
                "subject_id": rider["id"],
                "reason": "LATE_DELIVERY",
                "amount_cents": amount,
                "settlement_status": "PENDING",
                "order_id": order["id"],
                "assignment_id": a["id"],
                "created_at": clock.now_iso(),
            }
            store.fines[fine_obj["id"]] = fine_obj
            rider["wallet_balance_cents"] -= amount
        # Bonus tier recompute (and again after fine, per cascade)
        recompute_bonus_tier(rider)
        cascade.touch(rider, clock)
        cascade.touch(order, clock)

        # 8. RouteGroup completion check + rider AVAILABLE transition
        if a["route_group_id"]:
            group = store.route_groups[a["route_group_id"]]
            all_delivered = all(
                store.assignments[g_aid]["status"] == "DELIVERED"
                for g_aid in group["assignment_ids"]
            )
            if all_delivered:
                group["status"] = "COMPLETED"

        active_for_rider = any(
            other["rider_id"] == rider["id"] and other["status"] in {"OFFERED", "ACCEPTED", "PICKED_UP"}
            for other in store.assignments.values()
        )
        if not active_for_rider:
            rider["status"] = "AVAILABLE"
            cascade.touch(rider, clock)

    return envelope_object(a)


@bp.post("/assignments/<aid>/cancel")
def cancel_assignment(aid):
    uid, _ = require_role({"Rider"})
    store = get_store()
    clock = get_clock()
    with store.lock:
        a = _ensure_assignment(store, aid)
        if uid != a["rider_id"]:
            raise ApiError("ERR_FORBIDDEN", "not your assignment")
        if a["status"] != "ACCEPTED":
            raise ApiError("ERR_INVALID_STATE", "assignment not ACCEPTED")
        order = store.orders[a["order_id"]]
        if order["status"] == "PICKED_UP":
            raise ApiError("ERR_INVALID_STATE", "order already PICKED_UP")
        a["status"] = "CANCELLED"
        rider = store.riders[a["rider_id"]]
        # Create no-show fine
        fine_obj = {
            "id": new_uuid(),
            "subject_type": "RIDER",
            "subject_id": rider["id"],
            "reason": "RIDER_NO_SHOW",
            "amount_cents": 500,
            "settlement_status": "PENDING",
            "order_id": order["id"],
            "assignment_id": a["id"],
            "created_at": clock.now_iso(),
        }
        store.fines[fine_obj["id"]] = fine_obj
        rider["wallet_balance_cents"] -= 500
        recompute_bonus_tier(rider)

        # If rider has no other active assignments, go back to AVAILABLE
        active_for_rider = any(
            other["rider_id"] == rider["id"] and other["status"] in {"OFFERED", "ACCEPTED", "PICKED_UP"}
            for other in store.assignments.values()
            if other["id"] != a["id"]
        )
        if not active_for_rider and rider["status"] == "ON_DELIVERY":
            rider["status"] = "AVAILABLE"
        cascade.touch(rider, clock)

        # Redispatch a fresh offer
        if order["status"] in {"RESTAURANT_ACCEPTED", "PREPARING", "READY_FOR_PICKUP"}:
            open_dispatch(store, clock, order, force=True)
    return envelope_object(a)
