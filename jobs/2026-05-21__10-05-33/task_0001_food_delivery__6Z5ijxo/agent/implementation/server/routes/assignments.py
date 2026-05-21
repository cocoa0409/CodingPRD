from flask import Blueprint

from ..auth import require_role
from ..envelope import success
from ..errors import err
from ..repository import touch, body_or_empty, now_iso
from ..store import store
from ..domain.dispatch import dispatch_offer
from ..domain.rider_metrics import recompute_acceptance_rate, recompute_bonus_tier, recompute_on_time_rate
from ..domain.route_merge import maybe_merge_into_routegroup, complete_routegroup_if_done
from ..domain.fiscal import deliver_cascade
from ..domain.fines import create_fine

bp = Blueprint("assignments", __name__)


def _view(a):
    keys = (
        "id", "order_id", "rider_id", "status",
        "offered_at", "accepted_at", "picked_up_at", "delivered_at",
        "rejected_at", "cancelled_at",
        "route_group_id", "final_delivery_fee_cents",
        "created_at",
    )
    return {k: a.get(k) for k in keys}


@bp.get("/api/assignments/<aid>")
def get_assignment(aid):
    uid, role = require_role("PlatformAdmin", "Rider", "CustomerService")
    a = store.assignments.get(aid)
    if a is None:
        raise err("ERR_NOT_FOUND", "assignment not found")
    if role == "Rider" and a["rider_id"] != uid:
        raise err("ERR_FORBIDDEN", "not your assignment")
    return success(_view(a))


@bp.post("/api/assignments/<aid>/accept")
def accept_assignment(aid):
    uid, role = require_role("Rider")
    a = store.assignments.get(aid)
    if a is None:
        raise err("ERR_NOT_FOUND", "assignment not found")
    if a["rider_id"] != uid:
        raise err("ERR_FORBIDDEN", "not your assignment")
    rider = store.riders[a["rider_id"]]
    order = store.orders.get(a["order_id"])
    if order is None:
        raise err("ERR_NOT_FOUND", "order not found")
    if a["status"] != "OFFERED":
        raise err("ERR_INVALID_STATE", "not in OFFERED")
    if rider["status"] not in ("AVAILABLE", "ON_DELIVERY"):
        raise err("ERR_INVALID_STATE", "rider not available")
    if order["status"] not in ("RESTAURANT_ACCEPTED", "PREPARING", "READY_FOR_PICKUP"):
        raise err("ERR_INVALID_STATE", "order not in dispatchable state")
    # Uniqueness on order assignment. Per PRD's racing semantics, only ACCEPTED/PICKED_UP
    # block the accept — parallel OFFERED's must coexist briefly while two riders race.
    for other in store.assignments.values():
        if other["id"] == a["id"]:
            continue
        if other["order_id"] == order["id"] and other["status"] in ("ACCEPTED", "PICKED_UP"):
            raise err("ERR_ORDER_ALREADY_ASSIGNED", "order already has an active assignment")
    a["status"] = "ACCEPTED"
    a["accepted_at"] = now_iso()
    # Route merge consideration
    maybe_merge_into_routegroup(a, rider, order)
    # Cascade rider status
    if rider["status"] == "AVAILABLE":
        rider["status"] = "ON_DELIVERY"
    # Acceptance metric + tier
    recompute_acceptance_rate(rider)
    recompute_bonus_tier(rider)
    touch(rider)
    return success(_view(a))


@bp.post("/api/assignments/<aid>/reject")
def reject_assignment(aid):
    uid, role = require_role("Rider")
    a = store.assignments.get(aid)
    if a is None:
        raise err("ERR_NOT_FOUND", "assignment not found")
    if a["rider_id"] != uid:
        raise err("ERR_FORBIDDEN", "not your assignment")
    if a["status"] != "OFFERED":
        raise err("ERR_INVALID_STATE", "not in OFFERED")
    a["status"] = "REJECTED"
    a["rejected_at"] = now_iso()
    rider = store.riders[a["rider_id"]]
    recompute_acceptance_rate(rider)
    recompute_bonus_tier(rider)
    touch(rider)
    # Re-dispatch a fresh offer for the order
    order = store.orders.get(a["order_id"])
    if order and order["status"] in ("RESTAURANT_ACCEPTED", "PREPARING", "READY_FOR_PICKUP"):
        dispatch_offer(order)
    return success(_view(a))


@bp.post("/api/assignments/<aid>/pickup")
def pickup_assignment(aid):
    uid, role = require_role("Rider")
    a = store.assignments.get(aid)
    if a is None:
        raise err("ERR_NOT_FOUND", "assignment not found")
    if a["rider_id"] != uid:
        raise err("ERR_FORBIDDEN", "not your assignment")
    order = store.orders.get(a["order_id"])
    if order is None:
        raise err("ERR_NOT_FOUND", "order not found")
    if a["status"] != "ACCEPTED":
        raise err("ERR_INVALID_STATE", "not in ACCEPTED")
    if order["status"] != "READY_FOR_PICKUP":
        raise err("ERR_INVALID_STATE", "order not READY_FOR_PICKUP")
    a["status"] = "PICKED_UP"
    a["picked_up_at"] = now_iso()
    order["status"] = "PICKED_UP"
    touch(order)
    return success(_view(a))


@bp.post("/api/assignments/<aid>/deliver")
def deliver_assignment(aid):
    uid, role = require_role("Rider")
    a = store.assignments.get(aid)
    if a is None:
        raise err("ERR_NOT_FOUND", "assignment not found")
    if a["rider_id"] != uid:
        raise err("ERR_FORBIDDEN", "not your assignment")
    order = store.orders.get(a["order_id"])
    if order is None:
        raise err("ERR_NOT_FOUND", "order not found")
    if a["status"] != "PICKED_UP":
        raise err("ERR_INVALID_STATE", "not in PICKED_UP")
    if order["status"] != "PICKED_UP":
        raise err("ERR_INVALID_STATE", "order not in PICKED_UP")
    deliver_cascade(a, order)
    return success(_view(a))


@bp.post("/api/assignments/<aid>/cancel")
def cancel_assignment(aid):
    uid, role = require_role("Rider")
    a = store.assignments.get(aid)
    if a is None:
        raise err("ERR_NOT_FOUND", "assignment not found")
    if a["rider_id"] != uid:
        raise err("ERR_FORBIDDEN", "not your assignment")
    order = store.orders.get(a["order_id"])
    if order is None:
        raise err("ERR_NOT_FOUND", "order not found")
    if a["status"] != "ACCEPTED":
        raise err("ERR_INVALID_STATE", "not in ACCEPTED")
    if order["status"] == "PICKED_UP":
        raise err("ERR_INVALID_STATE", "order already picked up")
    a["status"] = "CANCELLED"
    a["cancelled_at"] = now_iso()
    rider = store.riders[a["rider_id"]]
    # No-show fine (debits wallet and recomputes tier as ledger side-effect)
    create_fine(
        subject_type="RIDER",
        subject_id=rider["id"],
        reason="RIDER_NO_SHOW",
        amount_cents=500,
        related_order_id=order["id"],
        related_assignment_id=a["id"],
    )
    # Rider status reconciliation (stays ON_DELIVERY if other live assignments remain)
    if rider["status"] == "ON_DELIVERY":
        has_live = any(x for x in store.assignments.values()
                       if x["rider_id"] == rider["id"]
                       and x["status"] in ("ACCEPTED", "PICKED_UP"))
        if not has_live:
            rider["status"] = "AVAILABLE"
    touch(rider)
    # If this assignment was in a route group, possibly complete or stay ACTIVE
    from ..domain.route_merge import complete_routegroup_if_done
    complete_routegroup_if_done(a.get("route_group_id"))
    # Re-dispatch a fresh offer for the order
    if order["status"] in ("RESTAURANT_ACCEPTED", "PREPARING", "READY_FOR_PICKUP"):
        dispatch_offer(order)
    return success(_view(a))


