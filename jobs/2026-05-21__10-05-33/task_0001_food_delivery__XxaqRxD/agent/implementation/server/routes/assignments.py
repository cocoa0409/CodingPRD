"""Assignment endpoints (rider-side)."""
from __future__ import annotations

from flask import Blueprint, g, request

from ..auth import require_role
from ..bonus import recompute_rider_metrics
from ..envelope import success_object
from ..errors import ApiError
from ..ids import new_uuid
from ..serializers import assignment_out
from ..services.dispatch import dispatch_for_order


bp = Blueprint("assignments", __name__, url_prefix="/api")


@bp.get("/assignments/<aid>")
def read_assignment(aid: str):
    require_role("PlatformAdmin", "Rider", "CustomerService")
    store = g.store
    a = store.assignments.get(aid)
    if not a:
        raise ApiError("ERR_NOT_FOUND")
    if g.user_role == "Rider" and g.user_id != a["rider_id"]:
        raise ApiError("ERR_FORBIDDEN")
    return success_object(store.clock, assignment_out(a))


@bp.post("/assignments/<aid>/accept")
def accept_assignment(aid: str):
    require_role("Rider")
    store = g.store
    with store.lock:
        a = store.assignments.get(aid)
        if not a:
            raise ApiError("ERR_NOT_FOUND")
        if g.user_id != a["rider_id"]:
            raise ApiError("ERR_FORBIDDEN")
        if a["status"] != "OFFERED":
            raise ApiError("ERR_INVALID_STATE")
        rider = store.riders[a["rider_id"]]
        if rider["status"] not in ("AVAILABLE", "ON_DELIVERY"):
            raise ApiError("ERR_INVALID_STATE")
        order = store.orders.get(a["order_id"])
        if not order:
            raise ApiError("ERR_NOT_FOUND")
        if order["status"] not in ("RESTAURANT_ACCEPTED", "PREPARING", "READY_FOR_PICKUP"):
            raise ApiError("ERR_INVALID_STATE")
        # Uniqueness: no other live Assignment on this order in OFFERED/ACCEPTED/PICKED_UP.
        for other_id, other in store.assignments.items():
            if other_id == aid:
                continue
            if other["order_id"] != a["order_id"]:
                continue
            if other["status"] in ("ACCEPTED", "PICKED_UP"):
                raise ApiError("ERR_ORDER_ALREADY_ASSIGNED")
        now_iso = store.now_iso()
        # Transition the assignment.
        a["status"] = "ACCEPTED"
        a["accepted_at"] = now_iso
        # Sibling OFFERED assignments for the same order become CANCELLED (PRD
        # implies first-writer-wins on uniqueness; other live offers are not
        # left orphaned because they would forever lose to this constraint).
        for other in store.assignments.values():
            if other["id"] == aid or other["order_id"] != a["order_id"]:
                continue
            if other["status"] == "OFFERED":
                other["status"] = "CANCELLED"
        # Record offer outcome ACCEPTED.
        rider["_offer_outcomes"].append("ACCEPTED")
        prev_status = rider["status"]
        if rider["status"] == "AVAILABLE":
            rider["status"] = "ON_DELIVERY"
        # Route-merge attempt.
        _attempt_route_merge(store, a, order, rider)
        # Recompute acceptance_rate (over last 30 offers).
        recompute_rider_metrics(rider)
        rider["version"] += 1
        rider["updated_at"] = now_iso
        return success_object(store.clock, assignment_out(a))


@bp.post("/assignments/<aid>/reject")
def reject_assignment(aid: str):
    require_role("Rider")
    store = g.store
    with store.lock:
        a = store.assignments.get(aid)
        if not a:
            raise ApiError("ERR_NOT_FOUND")
        if g.user_id != a["rider_id"]:
            raise ApiError("ERR_FORBIDDEN")
        if a["status"] != "OFFERED":
            raise ApiError("ERR_INVALID_STATE")
        a["status"] = "REJECTED"
        rider = store.riders[a["rider_id"]]
        rider["_offer_outcomes"].append("REJECTED")
        recompute_rider_metrics(rider)
        rider["version"] += 1
        rider["updated_at"] = store.now_iso()
        # Redispatch for the order.
        order = store.orders.get(a["order_id"])
        if order is not None and order["status"] in (
            "RESTAURANT_ACCEPTED",
            "PREPARING",
            "READY_FOR_PICKUP",
        ):
            dispatch_for_order(store, order)
        return success_object(store.clock, assignment_out(a))


@bp.post("/assignments/<aid>/pickup")
def pickup_assignment(aid: str):
    require_role("Rider")
    store = g.store
    with store.lock:
        a = store.assignments.get(aid)
        if not a:
            raise ApiError("ERR_NOT_FOUND")
        if g.user_id != a["rider_id"]:
            raise ApiError("ERR_FORBIDDEN")
        if a["status"] != "ACCEPTED":
            raise ApiError("ERR_INVALID_STATE")
        order = store.orders.get(a["order_id"])
        if not order or order["status"] != "READY_FOR_PICKUP":
            raise ApiError("ERR_INVALID_STATE")
        now_iso = store.now_iso()
        a["status"] = "PICKED_UP"
        a["picked_up_at"] = now_iso
        order["status"] = "PICKED_UP"
        order["version"] += 1
        order["updated_at"] = now_iso
        return success_object(store.clock, assignment_out(a))


@bp.post("/assignments/<aid>/deliver")
def deliver_assignment(aid: str):
    require_role("Rider")
    store = g.store
    with store.lock:
        a = store.assignments.get(aid)
        if not a:
            raise ApiError("ERR_NOT_FOUND")
        if g.user_id != a["rider_id"]:
            raise ApiError("ERR_FORBIDDEN")
        if a["status"] != "PICKED_UP":
            raise ApiError("ERR_INVALID_STATE")
        order = store.orders.get(a["order_id"])
        if not order or order["status"] != "PICKED_UP":
            raise ApiError("ERR_INVALID_STATE")
        from ..services.delivery import deliver_assignment as do_deliver
        do_deliver(store, a, order)
        return success_object(store.clock, assignment_out(a))


@bp.post("/assignments/<aid>/cancel")
def cancel_assignment(aid: str):
    require_role("Rider")
    store = g.store
    with store.lock:
        a = store.assignments.get(aid)
        if not a:
            raise ApiError("ERR_NOT_FOUND")
        if g.user_id != a["rider_id"]:
            raise ApiError("ERR_FORBIDDEN")
        if a["status"] != "ACCEPTED":
            raise ApiError("ERR_INVALID_STATE")
        order = store.orders.get(a["order_id"])
        if order is None:
            raise ApiError("ERR_NOT_FOUND")
        if order["status"] == "PICKED_UP":
            raise ApiError("ERR_INVALID_STATE")
        from ..services.delivery import cancel_after_accept
        cancel_after_accept(store, a, order)
        return success_object(store.clock, assignment_out(a))


# ---------- helpers --------------------------------------------------------


def _attempt_route_merge(store, assignment: dict, order: dict, rider: dict) -> None:
    """If a nearby unpicked assignment already in an ACTIVE route group exists,
    attach this assignment to the same group; otherwise leave route_group_id
    null (the platform never preemptively creates a group for a solo delivery).
    """
    from ..geo import haversine_m

    new_restaurant = store.restaurants.get(order["restaurant_id"])
    if not new_restaurant:
        return
    candidate_group_id: str | None = None
    for grp in store.route_groups.values():
        if grp["rider_id"] != rider["id"] or grp["status"] != "ACTIVE":
            continue
        for aid in grp["assignment_ids"]:
            other = store.assignments.get(aid)
            if not other or other["status"] not in ("OFFERED", "ACCEPTED"):
                continue
            o_order = store.orders.get(other["order_id"])
            if not o_order:
                continue
            o_rest = store.restaurants.get(o_order["restaurant_id"])
            if not o_rest:
                continue
            d = haversine_m(
                o_rest["lat"], o_rest["lng"], new_restaurant["lat"], new_restaurant["lng"]
            )
            if d <= 500.0:
                candidate_group_id = grp["id"]
                break
        if candidate_group_id:
            break
    if candidate_group_id is None:
        # Look for any sibling ACCEPTED assignment (without group yet) within 500m
        # belonging to this rider — that scenario should also form a group.
        for other in store.assignments.values():
            if other["id"] == assignment["id"]:
                continue
            if other["rider_id"] != rider["id"] or other["status"] not in (
                "OFFERED",
                "ACCEPTED",
            ):
                continue
            if other.get("route_group_id") is not None:
                continue
            o_order = store.orders.get(other["order_id"])
            if not o_order:
                continue
            o_rest = store.restaurants.get(o_order["restaurant_id"])
            if not o_rest:
                continue
            d = haversine_m(
                o_rest["lat"], o_rest["lng"], new_restaurant["lat"], new_restaurant["lng"]
            )
            if d <= 500.0:
                gid = new_uuid()
                now_iso = store.now_iso()
                grp = {
                    "id": gid,
                    "rider_id": rider["id"],
                    "assignment_ids": [other["id"], assignment["id"]],
                    "merged_at": now_iso,
                    "status": "ACTIVE",
                    "created_at": now_iso,
                }
                store.route_groups[gid] = grp
                other["route_group_id"] = gid
                assignment["route_group_id"] = gid
                return
        return
    grp = store.route_groups[candidate_group_id]
    grp["assignment_ids"].append(assignment["id"])
    assignment["route_group_id"] = candidate_group_id
