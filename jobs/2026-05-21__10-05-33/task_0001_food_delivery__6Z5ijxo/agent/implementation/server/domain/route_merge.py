from ..store import store
from ..repository import base_internal, now_iso
from ..geo import haversine_meters


def maybe_merge_into_routegroup(new_assignment, rider, new_order):
    """Called on acceptance. If the rider was already ON_DELIVERY and has an unpicked
    assignment within 500m of the new order's pickup, merge: attach to an existing
    RouteGroup if the peer is already in one, otherwise create a new RouteGroup with
    both assignments. Solo deliveries leave `route_group_id` null.
    """
    if rider["status"] != "ON_DELIVERY":
        return None  # promotion to ON_DELIVERY happens AFTER this call
    new_restaurant = store.restaurants[new_order["restaurant_id"]]

    peer = None
    for other in store.assignments.values():
        if other["id"] == new_assignment["id"]:
            continue
        if other["rider_id"] != rider["id"]:
            continue
        if other["status"] != "ACCEPTED":
            continue
        peer_order = store.orders.get(other["order_id"])
        if peer_order is None:
            continue
        peer_restaurant = store.restaurants.get(peer_order["restaurant_id"])
        if peer_restaurant is None:
            continue
        d = haversine_meters(
            new_restaurant["lat"], new_restaurant["lng"],
            peer_restaurant["lat"], peer_restaurant["lng"],
        )
        if d <= 500:
            peer = other
            break

    if peer is None:
        return None

    if peer.get("route_group_id"):
        rg = store.route_groups[peer["route_group_id"]]
        rg["assignment_ids"].append(new_assignment["id"])
        new_assignment["route_group_id"] = rg["id"]
        return rg

    rg = base_internal()
    rg.update({
        "rider_id": rider["id"],
        "assignment_ids": [peer["id"], new_assignment["id"]],
        "merged_at": now_iso(),
        "status": "ACTIVE",
    })
    store.route_groups[rg["id"]] = rg
    peer["route_group_id"] = rg["id"]
    new_assignment["route_group_id"] = rg["id"]
    return rg


def complete_routegroup_if_done(rg_id):
    if rg_id is None:
        return
    rg = store.route_groups.get(rg_id)
    if rg is None or rg["status"] != "ACTIVE":
        return
    for aid in rg["assignment_ids"]:
        a = store.assignments.get(aid)
        if a is None:
            continue
        if a["status"] not in ("DELIVERED", "CANCELLED"):
            return
    rg["status"] = "COMPLETED"
