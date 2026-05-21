"""Dispatch + assignment helpers.

Selects a candidate rider, opens an Assignment, attaches it to an existing
RouteGroup when the route-merge rule applies, and handles the 60-second
offer-timeout sweep that's invoked from `/api/_clock/advance`.
"""
from __future__ import annotations

from typing import Iterable

from ..clock import iso_z, parse_iso
from ..ids import new_uuid


# ---------- Public entry points --------------------------------------------


def dispatch_for_order(store, order: dict) -> dict | None:
    """Create an OFFERED Assignment for `order` targeting the best rider.

    Returns the new assignment dict, or None if no candidate exists. The
    caller decides whether None is an error condition.
    """
    rider = _pick_candidate_rider(store, order)
    if rider is None:
        return None
    return _create_assignment(store, order, rider)


def sweep_offer_timeouts(store) -> None:
    """Sweep any OFFERED Assignment whose age is >= 60s. Each swept assignment
    becomes REJECTED and triggers a fresh redispatch.
    """
    now = store.clock.now()
    expired_ids: list[str] = []
    for aid, a in store.assignments.items():
        if a["status"] != "OFFERED":
            continue
        offered_at = parse_iso(a["offered_at"])
        age = (now - offered_at).total_seconds()
        if age >= 60.0:
            expired_ids.append(aid)
    for aid in expired_ids:
        a = store.assignments[aid]
        a["status"] = "REJECTED"
        # Record offer outcome as REJECTED for the rider's acceptance_rate.
        rider = store.riders.get(a["rider_id"])
        if rider is not None:
            rider["_offer_outcomes"].append("REJECTED")
            from ..bonus import recompute_rider_metrics
            recompute_rider_metrics(rider)
            rider["version"] += 1
            rider["updated_at"] = store.now_iso()
        # Spawn a fresh offer for the same order if it is still in a dispatchable state.
        order = store.orders.get(a["order_id"])
        if order is None:
            continue
        if order["status"] in ("RESTAURANT_ACCEPTED", "PREPARING", "READY_FOR_PICKUP"):
            dispatch_for_order(store, order)


# ---------- Candidate selection --------------------------------------------


def _pick_candidate_rider(store, order: dict) -> dict | None:
    pool = []
    # Exclude riders with a live assignment on this order, and riders who have
    # already rejected (or timed-out into REJECTED) an offer for it — re-offering
    # the same rider after a refusal would loop indefinitely.
    excluded_rider_ids = {
        a["rider_id"]
        for a in store.assignments.values()
        if a["order_id"] == order["id"]
        and a["status"] in ("OFFERED", "ACCEPTED", "PICKED_UP", "REJECTED")
    }
    for r in store.riders.values():
        if r["id"] in excluded_rider_ids:
            continue
        if r["status"] not in ("AVAILABLE", "ON_DELIVERY"):
            continue
        pool.append(r)
    if not pool:
        return None
    restaurant = store.restaurants.get(order["restaurant_id"])
    if not restaurant:
        return None

    merge_ready: list[dict] = []
    available: list[dict] = []
    for r in pool:
        if r["status"] == "ON_DELIVERY" and _has_nearby_unpicked(store, r, restaurant):
            merge_ready.append(r)
        else:
            available.append(r)

    chosen_tier = merge_ready or available
    if not chosen_tier:
        return None
    # Tie-breakers: Rider.created_at descending, then id ascending.
    chosen_tier.sort(key=lambda r: (r["created_at"], r["id"]))
    chosen_tier.reverse()  # created_at descending
    # Stable: among ties on created_at we need id ascending — re-sort within ties.
    # Do a single sort key: (-created_at, id ascending). created_at is a string so
    # we cannot negate; sort with a custom key by sorting twice (stable).
    chosen_tier = sorted(chosen_tier, key=lambda r: r["id"])  # ascending id
    chosen_tier.sort(key=lambda r: r["created_at"], reverse=True)
    return chosen_tier[0]


def _has_nearby_unpicked(store, rider: dict, target_restaurant: dict) -> bool:
    from ..geo import haversine_m

    for group in store.route_groups.values():
        if group["rider_id"] != rider["id"] or group["status"] != "ACTIVE":
            continue
        for aid in group["assignment_ids"]:
            other = store.assignments.get(aid)
            if not other or other["status"] not in ("OFFERED", "ACCEPTED"):
                continue
            other_order = store.orders.get(other["order_id"])
            if not other_order:
                continue
            other_r = store.restaurants.get(other_order["restaurant_id"])
            if not other_r:
                continue
            d = haversine_m(
                other_r["lat"], other_r["lng"], target_restaurant["lat"], target_restaurant["lng"]
            )
            if d <= 500.0:
                return True
    return False


# ---------- Assignment creation --------------------------------------------


def _create_assignment(store, order: dict, rider: dict) -> dict:
    aid = new_uuid()
    now_iso = store.now_iso()
    a = {
        "id": aid,
        "order_id": order["id"],
        "rider_id": rider["id"],
        "status": "OFFERED",
        "offered_at": now_iso,
        "accepted_at": None,
        "picked_up_at": None,
        "delivered_at": None,
        "route_group_id": None,
        "final_delivery_fee_cents": None,
        "created_at": now_iso,
    }
    store.assignments[aid] = a
    return a
