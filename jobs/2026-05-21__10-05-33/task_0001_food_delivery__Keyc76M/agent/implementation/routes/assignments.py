"""Assignment endpoints: read, accept, reject, pickup, deliver, cancel."""

from flask import Blueprint, request

import auth
import envelope
import projection
import state
from services import dispatch as dispatch_svc
from services import delivery as delivery_svc
from services import fines as fines_svc
from services import orders as osvc
from services import riders as rsvc


bp = Blueprint("assignments", __name__)


@bp.route("/api/assignments/<aid>", methods=["GET"])
def get_assignment(aid):
    user_id, role = auth.headers()
    if not user_id:
        return envelope.auth_required()
    if role not in ("PlatformAdmin", "Rider", "CustomerService"):
        return envelope.forbidden()
    with state.lock():
        a = state.STORE.assignments.get(aid)
        if a is None:
            return envelope.not_found("Assignment not found.")
        if role == "Rider" and user_id != a["rider_id"]:
            return envelope.forbidden()
        return envelope.success(projection.render(a))


def _path_assignment_for_rider(aid, user_id):
    a = state.STORE.assignments.get(aid)
    if a is None:
        return None, envelope.not_found("Assignment not found.")
    if user_id != a["rider_id"]:
        return None, envelope.forbidden()
    return a, None


@bp.route("/api/assignments/<aid>/accept", methods=["POST"])
def accept(aid):
    user_id, role = auth.headers()
    if not user_id:
        return envelope.auth_required()
    if role != "Rider":
        return envelope.forbidden()
    with state.lock():
        a, err = _path_assignment_for_rider(aid, user_id)
        if err:
            return err
        if a["status"] != "OFFERED":
            return envelope.invalid_state("Assignment is not in OFFERED.")
        rider = state.STORE.riders[a["rider_id"]]
        if rider["status"] not in ("AVAILABLE", "ON_DELIVERY"):
            return envelope.invalid_state(
                "Rider must be AVAILABLE or ON_DELIVERY to accept."
            )
        order = state.STORE.orders.get(a["order_id"])
        if order is None:
            return envelope.not_found("Underlying order not found.")
        if order["status"] not in (
            "RESTAURANT_ACCEPTED", "PREPARING", "READY_FOR_PICKUP",
        ):
            return envelope.invalid_state(
                "Order is not in a state that accepts a rider acceptance."
            )
        # Uniqueness: any OTHER assignment for this order in ACCEPTED or PICKED_UP
        for other in state.STORE.assignments.values():
            if other["id"] == a["id"]:
                continue
            if other["order_id"] != a["order_id"]:
                continue
            if other["status"] in ("ACCEPTED", "PICKED_UP"):
                return envelope.error(
                    409, "ERR_ORDER_ALREADY_ASSIGNED",
                    "Another rider has already accepted this order.",
                )
        dispatch_svc.on_accept(a, order, rider)
        return envelope.success(projection.render(a))


@bp.route("/api/assignments/<aid>/reject", methods=["POST"])
def reject(aid):
    user_id, role = auth.headers()
    if not user_id:
        return envelope.auth_required()
    if role != "Rider":
        return envelope.forbidden()
    with state.lock():
        a, err = _path_assignment_for_rider(aid, user_id)
        if err:
            return err
        if a["status"] != "OFFERED":
            return envelope.invalid_state("Assignment is not in OFFERED.")
        rider = state.STORE.riders[a["rider_id"]]
        dispatch_svc.on_reject(a, rider, redispatch=True)
        return envelope.success(projection.render(a))


@bp.route("/api/assignments/<aid>/pickup", methods=["POST"])
def pickup(aid):
    user_id, role = auth.headers()
    if not user_id:
        return envelope.auth_required()
    if role != "Rider":
        return envelope.forbidden()
    with state.lock():
        a, err = _path_assignment_for_rider(aid, user_id)
        if err:
            return err
        if a["status"] != "ACCEPTED":
            return envelope.invalid_state("Assignment must be ACCEPTED to pickup.")
        order = state.STORE.orders.get(a["order_id"])
        if order is None or order["status"] != "READY_FOR_PICKUP":
            return envelope.invalid_state(
                "Order must be READY_FOR_PICKUP to pick up."
            )
        now = state.now()
        a["status"] = "PICKED_UP"
        a["picked_up_at"] = now
        order["status"] = "PICKED_UP"
        osvc.bump(order)
        return envelope.success(projection.render(a))


@bp.route("/api/assignments/<aid>/deliver", methods=["POST"])
def deliver(aid):
    user_id, role = auth.headers()
    if not user_id:
        return envelope.auth_required()
    if role != "Rider":
        return envelope.forbidden()
    with state.lock():
        a, err = _path_assignment_for_rider(aid, user_id)
        if err:
            return err
        if a["status"] != "PICKED_UP":
            return envelope.invalid_state("Assignment must be PICKED_UP to deliver.")
        order = state.STORE.orders.get(a["order_id"])
        if order is None or order["status"] != "PICKED_UP":
            return envelope.invalid_state(
                "Order must be PICKED_UP to deliver."
            )
        rider = state.STORE.riders[a["rider_id"]]
        delivery_svc.deliver(a, order, rider)
        return envelope.success(projection.render(a))


@bp.route("/api/assignments/<aid>/cancel", methods=["POST"])
def cancel(aid):
    user_id, role = auth.headers()
    if not user_id:
        return envelope.auth_required()
    if role != "Rider":
        return envelope.forbidden()
    with state.lock():
        a, err = _path_assignment_for_rider(aid, user_id)
        if err:
            return err
        if a["status"] != "ACCEPTED":
            return envelope.invalid_state("Assignment must be ACCEPTED to cancel.")
        order = state.STORE.orders.get(a["order_id"])
        if order is not None and order["status"] == "PICKED_UP":
            return envelope.invalid_state(
                "Cannot cancel after the order has been picked up."
            )
        rider = state.STORE.riders[a["rider_id"]]
        a["status"] = "CANCELLED"
        # RIDER_NO_SHOW fine = 500 cents flat.
        fines_svc.issue_rider_fine(
            rider, "RIDER_NO_SHOW", 500, related_order_id=a["order_id"],
        )
        # If rider has no other live assignments, return to AVAILABLE.
        if not rsvc.rider_has_blocking_assignments(rider["id"]) \
                and rider["status"] == "ON_DELIVERY":
            rider["status"] = "AVAILABLE"
            rsvc.bump(rider)
        # Issue a fresh offer for the same order.
        if order is not None and order["status"] in (
            "RESTAURANT_ACCEPTED", "PREPARING", "READY_FOR_PICKUP",
        ):
            dispatch_svc.dispatch_for_order(order)
        return envelope.success(projection.render(a))
