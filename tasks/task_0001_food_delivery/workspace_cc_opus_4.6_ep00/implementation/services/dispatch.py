from store import store
from models import make_unversioned
from services.computations import haversine_km


def find_best_rider(exclude_rider_ids=None):
    exclude = exclude_rider_ids or set()
    candidates = [
        r for r in store.riders.values()
        if r["status"] in ("AVAILABLE", "ON_DELIVERY") and r["id"] not in exclude
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda r: (-r["on_time_rate"], -r["acceptance_rate"], r["created_at"]))
    return candidates[0]


def dispatch_order(order):
    already_assigned = any(
        a["order_id"] == order["id"] and a["status"] in ("OFFERED", "ACCEPTED", "PICKED_UP")
        for a in store.assignments.values()
    )
    excluded = set()
    for a in store.assignments.values():
        if a["order_id"] == order["id"] and a["status"] in ("REJECTED", "CANCELLED"):
            excluded.add(a["rider_id"])

    rider = find_best_rider(excluded)
    if not rider:
        rider = find_best_rider()

    if not rider:
        return None

    assignment = make_unversioned({
        "order_id": order["id"],
        "rider_id": rider["id"],
        "route_group_id": None,
        "status": "OFFERED",
        "offered_at": assignment_now_str(),
        "accepted_at": None,
        "picked_up_at": None,
        "delivered_at": None,
        "final_delivery_fee_cents": None,
    })
    store.assignments[assignment["id"]] = assignment
    return assignment


def assignment_now_str():
    from clock import now, format_timestamp
    return format_timestamp(now())


def try_route_merge(assignment, rider):
    active_groups = [
        g for g in store.route_groups.values()
        if g["rider_id"] == rider["id"] and g["status"] == "ACTIVE"
    ]

    order = store.orders.get(assignment["order_id"])
    if not order:
        return

    restaurant = store.restaurants.get(order["restaurant_id"])
    if not restaurant:
        return

    for group in active_groups:
        for aid in group["assignment_ids"]:
            peer = store.assignments.get(aid)
            if not peer or peer["status"] in ("DELIVERED", "REJECTED", "CANCELLED"):
                continue
            if peer["status"] in ("PICKED_UP",):
                continue
            peer_order = store.orders.get(peer["order_id"])
            if not peer_order:
                continue
            peer_restaurant = store.restaurants.get(peer_order["restaurant_id"])
            if not peer_restaurant:
                continue
            dist = haversine_km(
                restaurant["lat"], restaurant["lng"],
                peer_restaurant["lat"], peer_restaurant["lng"],
            )
            dist_m = dist * 1000
            if dist_m <= 500:
                assignment["route_group_id"] = group["id"]
                group["assignment_ids"].append(assignment["id"])
                return

    for a in store.assignments.values():
        if a["id"] == assignment["id"]:
            continue
        if a["rider_id"] != rider["id"]:
            continue
        if a["status"] not in ("OFFERED", "ACCEPTED"):
            continue
        peer_order = store.orders.get(a["order_id"])
        if not peer_order:
            continue
        peer_restaurant = store.restaurants.get(peer_order["restaurant_id"])
        if not peer_restaurant:
            continue
        dist = haversine_km(
            restaurant["lat"], restaurant["lng"],
            peer_restaurant["lat"], peer_restaurant["lng"],
        )
        dist_m = dist * 1000
        if dist_m <= 500:
            from models import make_unversioned
            group = make_unversioned({
                "rider_id": rider["id"],
                "assignment_ids": [a["id"], assignment["id"]],
                "merged_at": assignment_now_str(),
                "status": "ACTIVE",
            })
            store.route_groups[group["id"]] = group
            a["route_group_id"] = group["id"]
            assignment["route_group_id"] = group["id"]
            return
