"""Dispatch logic — candidate selection and assignment creation.

The PRD §3.6 specifies a deterministic candidate ordering:
  1. Prefer a route-merge candidate (ON_DELIVERY with an ACTIVE RouteGroup
     containing an unpicked assignment within 500 m of this pickup) over a
     plain AVAILABLE candidate.
  2. Within the preference tier, tie-break by Rider.created_at descending,
     then Rider.id lexicographic ascending.

The function returns the freshly created Assignment, or None when the pool
is empty. Callers running `/dispatch` are responsible for surfacing
`ERR_INVALID_STATE` on a None return.
"""
from __future__ import annotations

from typing import Any

from . import cascade
from .geo import distance_metres
from .ids import new_uuid


_PICKUP_PROXIMITY_METRES = 500.0


def _excluded_riders(store, order_id: str) -> set[str]:
    """Riders already linked to a live assignment for this order — never re-offered."""
    excluded: set[str] = set()
    for a in store.assignments.values():
        if a["order_id"] == order_id and a["status"] in {"OFFERED", "ACCEPTED", "PICKED_UP"}:
            excluded.add(a["rider_id"])
    return excluded


def _has_unpicked_in_range(store, rider_id: str, pickup_lat: float, pickup_lng: float) -> bool:
    """True if the rider has any ACCEPTED leg whose pickup is within 500 m.

    The PRD ties this preference to riders for whom acceptance would trigger
    the route-merge rule — that rule fires whenever a live ACCEPTED peer is
    within 500 m, irrespective of whether a RouteGroup already exists.
    """
    for a in store.assignments.values():
        if a["rider_id"] != rider_id:
            continue
        if a["status"] != "ACCEPTED":
            continue
        order = store.orders.get(a["order_id"])
        if not order:
            continue
        restaurant = store.restaurants.get(order["restaurant_id"])
        if not restaurant:
            continue
        if distance_metres(
            restaurant["lat"], restaurant["lng"], pickup_lat, pickup_lng
        ) <= _PICKUP_PROXIMITY_METRES:
            return True
    return False


def _eligible_candidates(store, order: dict[str, Any]) -> list[dict[str, Any]]:
    excluded = _excluded_riders(store, order["id"])
    restaurant = store.restaurants[order["restaurant_id"]]
    pool: list[dict[str, Any]] = []
    for rider in store.riders.values():
        if rider["id"] in excluded:
            continue
        if rider["status"] not in {"AVAILABLE", "ON_DELIVERY"}:
            continue
        pool.append(rider)
    return pool


def _select_best(store, order: dict[str, Any]) -> dict[str, Any] | None:
    pool = _eligible_candidates(store, order)
    if not pool:
        return None
    restaurant = store.restaurants[order["restaurant_id"]]

    def merge_eligible(r):
        if r["status"] != "ON_DELIVERY":
            return False
        return _has_unpicked_in_range(store, r["id"], restaurant["lat"], restaurant["lng"])

    # Preference 1: route-merge eligible
    merge_tier = [r for r in pool if merge_eligible(r)]
    if merge_tier:
        merge_tier.sort(key=lambda r: (-_created_at_key(r), r["id"]))
        return merge_tier[0]

    other = [r for r in pool if not merge_eligible(r)]
    other.sort(key=lambda r: (-_created_at_key(r), r["id"]))
    return other[0] if other else None


def _created_at_key(rider: dict[str, Any]) -> float:
    # Sort newest first means we want larger created_at to come first;
    # negate so we can stay in ascending order. Use ISO string compare
    # (lex order matches chronological for our format).
    s = rider["created_at"]
    # Encode the string into a sortable integer-ish number; simplest is to
    # rely on the string-compare on isoformat. We do that by returning a
    # tuple key in select_best directly. This helper isn't used.
    return _iso_to_epoch(s)


def _iso_to_epoch(s: str) -> float:
    from .clock import parse_iso
    return parse_iso(s).timestamp()


def open_dispatch(store, clock, order, *, force: bool = False):
    """Create a fresh OFFERED Assignment if a candidate exists; else return None.

    `force=False` is used by /start-preparing — it is a no-op when an
    assignment is already live (OFFERED/ACCEPTED/PICKED_UP) for the order.
    `force=True` is used by /dispatch — it always creates a new offer when
    a candidate exists, regardless of other live assignments.
    """
    if not force:
        for a in store.assignments.values():
            if a["order_id"] == order["id"] and a["status"] in {"OFFERED", "ACCEPTED", "PICKED_UP"}:
                return None
    rider = _select_best(store, order)
    if rider is None:
        return None
    now = clock.now_iso()
    assignment = {
        "id": new_uuid(),
        "order_id": order["id"],
        "rider_id": rider["id"],
        "status": "OFFERED",
        "offered_at": now,
        "accepted_at": None,
        "picked_up_at": None,
        "delivered_at": None,
        "route_group_id": None,
        "final_delivery_fee_cents": None,
        "created_at": now,
    }
    store.assignments[assignment["id"]] = assignment
    return assignment
