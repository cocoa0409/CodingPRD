"""Dispatch and route-merge logic."""

import compute
import state
from services import riders as rsvc


def _eligible_riders_for_order(order):
    """Candidates per §3.6:
    - status AVAILABLE or ON_DELIVERY
    - SUSPENDED/OFFLINE excluded
    - any rider with a prior assignment (any status) for this same order
      is excluded — once rejected/cancelled/timed-out, a rider does not
      get re-offered the same order.
    """
    blocked = {
        a["rider_id"]
        for a in state.STORE.assignments.values()
        if a["order_id"] == order["id"]
    }
    out = []
    for r in state.STORE.riders.values():
        if r["status"] not in ("AVAILABLE", "ON_DELIVERY"):
            continue
        if r["id"] in blocked:
            continue
        out.append(r)
    return out


def _rider_has_unpicked_nearby(rider, order):
    """True if rider has any ACCEPTED assignment whose pickup restaurant is
    within 500m of the new order's pickup restaurant.
    """
    target = state.STORE.restaurants[order["restaurant_id"]]
    for a in state.STORE.assignments.values():
        if a["rider_id"] != rider["id"]:
            continue
        if a["status"] != "ACCEPTED":
            continue
        peer_order = state.STORE.orders.get(a["order_id"])
        if peer_order is None:
            continue
        peer_rest = state.STORE.restaurants.get(peer_order["restaurant_id"])
        if peer_rest is None:
            continue
        d_m = compute.haversine_meters(
            target["lat"], target["lng"],
            peer_rest["lat"], peer_rest["lng"],
        )
        if d_m <= 500.0:
            return True
    return False


def _select_best_rider(order):
    candidates = _eligible_riders_for_order(order)
    if not candidates:
        return None
    merge_tier = []
    other_tier = []
    for r in candidates:
        if r["status"] == "ON_DELIVERY" and _rider_has_unpicked_nearby(r, order):
            merge_tier.append(r)
        else:
            other_tier.append(r)
    pool = merge_tier if merge_tier else other_tier
    pool.sort(key=lambda r: (-r["created_at"].timestamp(), r["id"]))
    return pool[0]


def _new_route_group(rider_id, assignment_ids):
    gid = state.gen_id()
    now = state.now()
    rg = {
        "id": gid,
        "rider_id": rider_id,
        "assignment_ids": list(assignment_ids),
        "merged_at": now,
        "status": "ACTIVE",
        "created_at": now,
    }
    state.STORE.route_groups[gid] = rg
    return rg


def dispatch_for_order(order):
    rider = _select_best_rider(order)
    if rider is None:
        return None
    now = state.now()
    aid = state.gen_id()
    assignment = {
        "id": aid,
        "order_id": order["id"],
        "rider_id": rider["id"],
        "status": "OFFERED",
        "route_group_id": None,
        "final_delivery_fee_cents": None,
        "offered_at": now,
        "accepted_at": None,
        "picked_up_at": None,
        "delivered_at": None,
        "created_at": now,
    }
    state.STORE.assignments[aid] = assignment
    return assignment


def _attempt_merge(new_assignment, rider, order):
    """Merge new_assignment into the rider's set of unpicked assignments,
    creating a RouteGroup on the first merge.
    """
    target = state.STORE.restaurants[order["restaurant_id"]]
    for peer_a in state.STORE.assignments.values():
        if peer_a["id"] == new_assignment["id"]:
            continue
        if peer_a["rider_id"] != rider["id"]:
            continue
        if peer_a["status"] != "ACCEPTED":
            continue
        peer_order = state.STORE.orders.get(peer_a["order_id"])
        if peer_order is None:
            continue
        peer_rest = state.STORE.restaurants.get(peer_order["restaurant_id"])
        if peer_rest is None:
            continue
        d_m = compute.haversine_meters(
            target["lat"], target["lng"],
            peer_rest["lat"], peer_rest["lng"],
        )
        if d_m > 500.0:
            continue
        # Eligible merge partner found.
        if peer_a.get("route_group_id"):
            rg = state.STORE.route_groups[peer_a["route_group_id"]]
            if new_assignment["id"] not in rg["assignment_ids"]:
                rg["assignment_ids"].append(new_assignment["id"])
            new_assignment["route_group_id"] = rg["id"]
        else:
            rg = _new_route_group(rider["id"], [peer_a["id"], new_assignment["id"]])
            peer_a["route_group_id"] = rg["id"]
            new_assignment["route_group_id"] = rg["id"]
        return


def on_accept(assignment, order, rider):
    assignment["status"] = "ACCEPTED"
    assignment["accepted_at"] = state.now()
    rsvc.record_offer_outcome(rider["id"], accepted=True)
    rsvc.recompute_acceptance_rate(rider)
    if rider["status"] == "AVAILABLE":
        rider["status"] = "ON_DELIVERY"
    rsvc.recompute_bonus_tier(rider)
    rsvc.bump(rider)
    _attempt_merge(assignment, rider, order)
    return assignment


def on_reject(assignment, rider, redispatch=True):
    assignment["status"] = "REJECTED"
    rsvc.record_offer_outcome(rider["id"], accepted=False)
    rsvc.recompute_acceptance_rate(rider)
    rsvc.recompute_bonus_tier(rider)
    rsvc.bump(rider)
    if redispatch:
        order = state.STORE.orders.get(assignment["order_id"])
        if order and order["status"] in (
            "RESTAURANT_ACCEPTED", "PREPARING", "READY_FOR_PICKUP",
        ):
            dispatch_for_order(order)
