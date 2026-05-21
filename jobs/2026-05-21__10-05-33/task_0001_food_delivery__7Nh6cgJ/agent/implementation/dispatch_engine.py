"""Dispatch / assignment / route-merging engine. Stubs filled in incrementally."""

from __future__ import annotations

from datetime import datetime

from clock import CLOCK
from errors import APIError
from geo import haversine_km
from ids import new_id
from resources import make_simple, touch
from store import STORE


def _parse_iso(value: str) -> datetime:
    # Accepts "...Z" suffix.
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    return datetime.fromisoformat(value)


def _is_unpicked(assignment: dict) -> bool:
    return assignment["status"] in ("OFFERED", "ACCEPTED")


def _restaurant_for(order: dict) -> dict:
    return STORE.restaurants[order["restaurant_id"]]


def _live_assignment_for_order(order_id: str) -> dict | None:
    for a in STORE.assignments.values():
        if a["order_id"] == order_id and a["status"] in ("OFFERED", "ACCEPTED", "PICKED_UP"):
            return a
    return None


def _rider_holds_live(rider_id: str, order_id: str) -> bool:
    for a in STORE.assignments.values():
        if (a["rider_id"] == rider_id and a["order_id"] == order_id
                and a["status"] in ("OFFERED", "ACCEPTED", "PICKED_UP")):
            return True
    return False


def _active_route_group_for(rider_id: str) -> dict | None:
    for g in STORE.route_groups.values():
        if g["rider_id"] == rider_id and g["status"] == "ACTIVE":
            return g
    return None


def _candidate_pool(order: dict) -> list[dict]:
    """Pick the best candidate rider per dispatch rules; return ordered list."""
    restaurant = _restaurant_for(order)
    eligible = []
    for rider in STORE.riders.values():
        if rider["status"] not in ("AVAILABLE", "ON_DELIVERY"):
            continue
        if _rider_holds_live(rider["id"], order["id"]):
            continue
        eligible.append(rider)

    def sort_key(rider: dict):
        # 0 = preferred (merge-eligible ON_DELIVERY), 1 = otherwise
        merge_pref = 1
        if rider["status"] == "ON_DELIVERY":
            group = _active_route_group_for(rider["id"])
            if group is not None:
                for aid in group["assignment_ids"]:
                    a = STORE.assignments.get(aid)
                    if a is None or not _is_unpicked(a):
                        continue
                    other_order = STORE.orders.get(a["order_id"])
                    if other_order is None:
                        continue
                    other_rest = STORE.restaurants.get(other_order["restaurant_id"])
                    if other_rest is None:
                        continue
                    d_m = haversine_km(restaurant["lat"], restaurant["lng"],
                                        other_rest["lat"], other_rest["lng"]) * 1000.0
                    if d_m <= 500.0:
                        merge_pref = 0
                        break
        # tie-break: created_at DESC, then id ASC
        return (merge_pref, _negate_iso(rider["created_at"]), rider["id"])

    eligible.sort(key=sort_key)
    return eligible


def _negate_iso(ts: str) -> str:
    """Return a key that sorts DESC by ts when used in ASC sort context."""
    # Invert each char using ord arithmetic: easiest is to use a tuple with negated epoch.
    dt = _parse_iso(ts)
    return -dt.timestamp()


def open_dispatch(order: dict) -> dict | None:
    """Create a fresh OFFERED Assignment for order, or return None when no candidates."""
    pool = _candidate_pool(order)
    if not pool:
        return None
    rider = pool[0]
    now = CLOCK.now_iso()
    assignment = make_simple({
        "order_id": order["id"],
        "rider_id": rider["id"],
        "status": "OFFERED",
        "offered_at": now,
        "accepted_at": None,
        "picked_up_at": None,
        "delivered_at": None,
        "final_delivery_fee_cents": None,
        "route_group_id": None,
    })
    STORE.assignments[assignment["id"]] = assignment
    return assignment


def force_dispatch(order: dict) -> dict:
    """Dispatch a fresh assignment; raise ERR_INVALID_STATE when no candidates."""
    assignment = open_dispatch(order)
    if assignment is None:
        raise APIError("ERR_INVALID_STATE", "No eligible rider available for dispatch.")
    return assignment


def sweep_offer_timeouts() -> None:
    """Move any OFFERED assignment >= 60s old to REJECTED and redispatch."""
    now = CLOCK.now()
    affected: list[dict] = []
    for assignment in list(STORE.assignments.values()):
        if assignment["status"] != "OFFERED":
            continue
        offered = _parse_iso(assignment["offered_at"])
        if (now - offered).total_seconds() >= 60.0:
            affected.append(assignment)

    for assignment in affected:
        assignment["status"] = "REJECTED"
        # No version on Assignment; just recompute rider acceptance_rate.
        rider = STORE.riders.get(assignment["rider_id"])
        if rider is not None:
            from rider_metrics import recompute_acceptance_rate
            recompute_acceptance_rate(rider)
            touch(rider)
        order = STORE.orders.get(assignment["order_id"])
        # Redispatch only when the order still needs a rider.
        if order is None:
            continue
        if order["status"] in ("RESTAURANT_ACCEPTED", "PREPARING", "READY_FOR_PICKUP"):
            if _live_assignment_for_order(order["id"]) is None:
                open_dispatch(order)
