from ..store import store
from ..repository import base_internal, now_iso
from ..geo import haversine_meters


def _excluded_riders_for_order(order_id: str) -> set:
    """Riders who already hold a live assignment for the same order."""
    out = set()
    for a in store.assignments.values():
        if a["order_id"] == order_id and a["status"] in ("OFFERED", "ACCEPTED", "PICKED_UP"):
            out.add(a["rider_id"])
    return out


def _rider_has_nearby_unpicked(rider, new_restaurant) -> bool:
    """True if rider's ACTIVE RouteGroup contains an unpicked assignment whose
    restaurant is within 500 metres of new_restaurant."""
    for rg in store.route_groups.values():
        if rg["rider_id"] != rider["id"] or rg["status"] != "ACTIVE":
            continue
        for aid in rg["assignment_ids"]:
            a = store.assignments.get(aid)
            if a is None:
                continue
            if a["status"] != "ACCEPTED":
                continue
            other_order = store.orders.get(a["order_id"])
            if other_order is None:
                continue
            other_restaurant = store.restaurants.get(other_order["restaurant_id"])
            if other_restaurant is None:
                continue
            d = haversine_meters(
                new_restaurant["lat"], new_restaurant["lng"],
                other_restaurant["lat"], other_restaurant["lng"],
            )
            if d <= 500:
                return True
    return False


def _select_candidate(order):
    excluded = _excluded_riders_for_order(order["id"])
    restaurant = store.restaurants[order["restaurant_id"]]
    pool = [r for r in store.riders.values()
            if r["status"] in ("AVAILABLE", "ON_DELIVERY")
            and r["id"] not in excluded]
    if not pool:
        return None

    tier1 = [r for r in pool
             if r["status"] == "ON_DELIVERY"
             and _rider_has_nearby_unpicked(r, restaurant)]
    bucket = tier1 if tier1 else pool

    # Stable-sort: tiebreak by id ASC first, then primary by created_at DESC.
    bucket = sorted(bucket, key=lambda r: r["id"])
    bucket = sorted(bucket, key=lambda r: r["created_at"], reverse=True)
    return bucket[0]


def dispatch_offer(order):
    """Create a new OFFERED Assignment for `order`. Returns None if no rider."""
    rider = _select_candidate(order)
    if rider is None:
        return None
    a = base_internal()
    a.update({
        "order_id": order["id"],
        "rider_id": rider["id"],
        "status": "OFFERED",
        "offered_at": now_iso(),
        "accepted_at": None,
        "picked_up_at": None,
        "delivered_at": None,
        "rejected_at": None,
        "cancelled_at": None,
        "route_group_id": None,
        "final_delivery_fee_cents": None,
    })
    store.assignments[a["id"]] = a
    return a
