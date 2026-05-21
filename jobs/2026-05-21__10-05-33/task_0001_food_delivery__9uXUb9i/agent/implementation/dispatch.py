"""Rider selection and route-merge logic (PRD §3.6)."""
from __future__ import annotations

from typing import Optional

import store
from common import haversine_m
from errors import ApiError
from store import gen_id, iso_z, now


PROXIMITY_M = 500.0


def _rider_has_live_assignment_for_order(rider_id: str, order_id: str) -> bool:
    for a in store.assignments.values():
        if (
            a["order_id"] == order_id
            and a["rider_id"] == rider_id
            and a["status"] in ("OFFERED", "ACCEPTED", "PICKED_UP")
        ):
            return True
    return False


def _has_proximity_merge_candidate(rider_id: str, pickup_lat: float, pickup_lng: float) -> bool:
    """Return True iff the rider holds an ACTIVE RouteGroup with at least one unpicked
    assignment whose pickup restaurant is within 500m of (pickup_lat, pickup_lng).
    """
    for g in store.route_groups.values():
        if g["rider_id"] != rider_id or g["status"] != "ACTIVE":
            continue
        for aid in g["assignment_ids"]:
            a = store.assignments.get(aid)
            if not a:
                continue
            if a["status"] not in ("OFFERED", "ACCEPTED"):
                # Only unpicked legs count; PICKED_UP/DELIVERED do not.
                continue
            o = store.orders.get(a["order_id"])
            if not o:
                continue
            rest = store.restaurants.get(o["restaurant_id"])
            if not rest:
                continue
            d = haversine_m(rest["lat"], rest["lng"], pickup_lat, pickup_lng)
            if d <= PROXIMITY_M:
                return True
    return False


def _select_rider(order: dict) -> Optional[str]:
    """Pick the best candidate rider id for this order, or None if pool is empty."""
    rest = store.restaurants[order["restaurant_id"]]
    pickup_lat, pickup_lng = rest["lat"], rest["lng"]

    candidates = []
    for r in store.riders.values():
        if r["status"] not in ("AVAILABLE", "ON_DELIVERY"):
            continue
        # Exclude riders already holding a live Assignment for this order.
        if _rider_has_live_assignment_for_order(r["id"], order["id"]):
            continue
        candidates.append(r)
    if not candidates:
        return None

    def sort_key(r):
        merge_eligible = (
            r["status"] == "ON_DELIVERY"
            and _has_proximity_merge_candidate(r["id"], pickup_lat, pickup_lng)
        )
        # Higher merge_eligible first; then created_at descending; then id ascending.
        # We want sort ascending overall, so negate as needed.
        return (
            0 if merge_eligible else 1,
            # created_at descending: invert by negative? created_at is ISO string,
            # we can flip via reverse sort separately.
            -_iso_ord(r["created_at"]),
            r["id"],
        )

    candidates.sort(key=sort_key)
    return candidates[0]["id"]


def _iso_ord(iso_str: str) -> float:
    """Convert ISO Z timestamp to a sortable float (Unix seconds)."""
    from datetime import datetime, timezone

    if iso_str.endswith("Z"):
        iso_str = iso_str[:-1] + "+00:00"
    return datetime.fromisoformat(iso_str).replace(tzinfo=timezone.utc).timestamp()


def open_dispatch_offer(order: dict, *, raise_on_empty: bool = False) -> Optional[dict]:
    """Create a fresh OFFERED Assignment for the order, or None if no candidate.

    Returns the created assignment (or None). When `raise_on_empty` is True and
    no candidate exists, raises ERR_INVALID_STATE per PRD §3.6.
    """
    rid = _select_rider(order)
    if rid is None:
        if raise_on_empty:
            raise ApiError("ERR_INVALID_STATE", "No available rider for dispatch.")
        return None
    t = now()
    aid = gen_id()
    a = {
        "id": aid,
        "order_id": order["id"],
        "rider_id": rid,
        "status": "OFFERED",
        "offered_at": iso_z(t),
        "accepted_at": None,
        "picked_up_at": None,
        "delivered_at": None,
        "route_group_id": None,
        "final_delivery_fee_cents": None,
        "created_at": iso_z(t),
    }
    store.assignments[aid] = a
    return a
