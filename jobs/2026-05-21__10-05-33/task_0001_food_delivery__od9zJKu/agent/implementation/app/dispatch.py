"""Dispatch logic: candidate selection, route-merge eligibility, assignment creation."""
from __future__ import annotations

from functools import cmp_to_key

from .clock import iso_now
from .entities import init_unversioned
from .envelope import err_invalid_state
from .geo import haversine_km
from .store import store


ROUTE_MERGE_RADIUS_KM = 0.5
DISPATCH_OFFER_TIMEOUT_SECONDS = 60


def _has_any_assignment_for_order(rider_id: str, order_id: str) -> bool:
    """Exclude a rider from re-dispatch if they ever held an Assignment for this order
    (active or terminal). PRD: 'never re-offers an order to a rider who already holds it'
    interpreted as 'who has ever held' so re-dispatches reach a different rider."""
    for a in store.assignments.values():
        if a["rider_id"] == rider_id and a["order_id"] == order_id:
            return True
    return False


def _rider_has_unpicked_within_radius(rider_id: str, order: dict) -> bool:
    """Does the rider have an ACTIVE RouteGroup containing at least one unpicked
    assignment whose pickup restaurant is within 500m of the new order's pickup restaurant?"""
    # Pickup restaurant of new order
    target_rest = store.restaurants[order["restaurant_id"]]
    for grp in store.route_groups.values():
        if grp["rider_id"] != rider_id or grp["status"] != "ACTIVE":
            continue
        for aid in grp["assignment_ids"]:
            a = store.assignments.get(aid)
            if not a:
                continue
            if a["status"] not in ("OFFERED", "ACCEPTED"):  # "unpicked"
                continue
            other_order = store.orders.get(a["order_id"])
            if not other_order:
                continue
            other_rest = store.restaurants[other_order["restaurant_id"]]
            d_km = haversine_km(
                target_rest["lat"], target_rest["lng"], other_rest["lat"], other_rest["lng"]
            )
            if d_km <= ROUTE_MERGE_RADIUS_KM:
                return True
    return False


def _select_rider_for_order(order: dict) -> dict | None:
    """Apply the candidate-selection algorithm and return the chosen rider, or None."""
    candidates = []
    for rider in store.riders.values():
        if rider["status"] not in ("AVAILABLE", "ON_DELIVERY"):
            continue
        if _has_any_assignment_for_order(rider["id"], order["id"]):
            continue
        candidates.append(rider)
    if not candidates:
        return None

    # Tier 1: ON_DELIVERY riders with route-merge eligibility for this order
    # Tier 2: AVAILABLE riders
    # (Note: ON_DELIVERY riders WITHOUT merge eligibility are also fine candidates,
    #  but the spec says merge-eligible-ON_DELIVERY is preferred over AVAILABLE.
    #  Plain ON_DELIVERY without merge isn't called out explicitly as a tier.)
    # PRD: "prefers any rider in ON_DELIVERY whose existing ACTIVE RouteGroup already
    # contains at least one unpicked assignment ... within 500 metres ... over any rider in AVAILABLE."
    # So: tier 1 = merge-eligible ON_DELIVERY; tier 2 = all others.

    def tier_of(r: dict) -> int:
        if r["status"] == "ON_DELIVERY" and _rider_has_unpicked_within_radius(r["id"], order):
            return 0
        return 1

    def cmp(a: dict, b: dict) -> int:
        ta, tb = tier_of(a), tier_of(b)
        if ta != tb:
            return -1 if ta < tb else 1
        # created_at descending
        if a["created_at"] != b["created_at"]:
            return -1 if a["created_at"] > b["created_at"] else 1
        # id lex smallest
        if a["id"] != b["id"]:
            return -1 if a["id"] < b["id"] else 1
        return 0

    candidates.sort(key=cmp_to_key(cmp))
    return candidates[0]


def open_dispatch(order: dict) -> dict:
    """Create a fresh OFFERED Assignment for `order`. Returns the assignment.
    Raises ERR_INVALID_STATE if no candidate is found."""
    rider = _select_rider_for_order(order)
    if not rider:
        raise err_invalid_state("No available rider for dispatch")
    a = init_unversioned("Assignment")
    a.update(
        {
            "order_id": order["id"],
            "rider_id": rider["id"],
            "status": "OFFERED",
            "offered_at": iso_now(),
            "accepted_at": None,
            "picked_up_at": None,
            "delivered_at": None,
            "route_group_id": None,
            "final_delivery_fee_cents": None,
        }
    )
    store.assignments[a["id"]] = a
    return a
