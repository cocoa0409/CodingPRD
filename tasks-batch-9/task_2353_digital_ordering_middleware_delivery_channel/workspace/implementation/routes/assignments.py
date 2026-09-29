"""Delivery assignments: offer lifecycle, handoff SLA and delivery."""
import math

from flask import Blueprint

import clock
import db
import errors
import middleware as M
import response
import validation
from errors import fail
from routes import common
from services import constants as K
from services import domain, serializers

bp = Blueprint("assignments", __name__)


def _scope(assignment):
    M.require_network_scope(assignment["courier_network_id"])
    order = db.orders.get(assignment["order_id"])
    if order is not None:
        M.require_store_scope(order["store_id"])
    return order


@bp.get("/delivery-assignments/<assignment_id>")
@M.endpoint(M.PLATFORM_ADMIN, M.STORE_OPERATOR, M.COURIER_AGENT, M.SETTLEMENT_ANALYST)
def read_assignment(assignment_id):
    assignment = common.get_assignment(assignment_id)
    _scope(assignment)
    return response.object_response(serializers.assignment(assignment))


@bp.get("/delivery-assignments")
@M.endpoint(M.PLATFORM_ADMIN, M.STORE_OPERATOR, M.COURIER_AGENT, M.SETTLEMENT_ANALYST)
def list_assignments():
    limit, offset = validation.pagination()
    order_id = validation.query_str("order_id")
    network_id = validation.query_str("courier_network_id")
    state = validation.query_enum("state", K.ASSIGNMENT_STATES)

    def keep(rec):
        if order_id is not None and rec["order_id"] != order_id:
            return False
        if network_id is not None and rec["courier_network_id"] != network_id:
            return False
        if state is not None and rec["state"] != state:
            return False
        return True

    records = db.sorted_records(db.assignments, keep)
    page, meta = response.paginate(records, limit, offset)
    return response.array_response([serializers.assignment(r) for r in page], meta)


@bp.post("/delivery-assignments/<assignment_id>/accept")
@M.endpoint(M.COURIER_AGENT)
def accept_assignment(assignment_id):
    assignment = common.get_assignment(assignment_id)
    order = _scope(assignment)

    if assignment["state"] != "OFFERED":
        fail(errors.ERR_INVALID_ASSIGNMENT_STATE)
    network = db.courier_networks.get(assignment["courier_network_id"])
    if network is None or not network["is_active"]:
        fail(errors.ERR_INVALID_ASSIGNMENT_STATE)
    if order is None or order["injection_status"] not in ("ACCEPTED", "TABLET_FALLBACK"):
        fail(errors.ERR_ORDER_NOT_INJECTED)
    occupancy = domain.occupancy_count(network["id"],
                                       exclude_assignment_id=assignment["id"])
    if occupancy >= network["max_concurrent_assignments"]:
        fail(errors.ERR_NETWORK_AT_CAPACITY)

    accepted_at = clock.now()
    deadline = clock.plus_seconds(accepted_at, network["handoff_sla_seconds"])
    assignment["state"] = "ACCEPTED"
    assignment["accepted_at"] = accepted_at
    assignment["handoff_deadline_at"] = deadline
    assignment["occupancy_until"] = clock.plus_seconds(
        deadline, network["dispatch_buffer_seconds"])
    assignment["delivery_fee_cents"] = network["per_delivery_fee_cents"]
    db.touch(assignment)
    domain.recompute_network_open_assignments(network)
    return response.object_response(serializers.assignment(assignment))


@bp.post("/delivery-assignments/<assignment_id>/decline")
@M.endpoint(M.COURIER_AGENT)
def decline_assignment(assignment_id):
    payload = validation.body()
    validation.opt_str(payload, "reason_code")
    assignment = common.get_assignment(assignment_id)
    _scope(assignment)

    if assignment["state"] != "OFFERED":
        fail(errors.ERR_INVALID_ASSIGNMENT_STATE)

    assignment["state"] = "DECLINED"
    assignment["occupancy_until"] = clock.now()
    db.touch(assignment)
    domain.recompute_network_open_assignments(
        db.courier_networks.get(assignment["courier_network_id"]))
    return response.object_response(serializers.assignment(assignment))


@bp.post("/delivery-assignments/<assignment_id>/handoff")
@M.endpoint(M.COURIER_AGENT)
def handoff_assignment(assignment_id):
    assignment = common.get_assignment(assignment_id)
    order = _scope(assignment)

    if assignment["state"] != "ACCEPTED":
        fail(errors.ERR_INVALID_ASSIGNMENT_STATE)
    if order is None or order["fulfillment_status"] != "READY":
        fail(errors.ERR_ORDER_NOT_READY)

    handoff_at = clock.now()
    deadline = assignment["handoff_deadline_at"]
    lateness = 0
    if deadline is not None:
        lateness = max(0, int(math.floor((handoff_at - deadline).total_seconds())))
    penalty = domain.handoff_penalty_cents(lateness)

    assignment["state"] = "HANDED_OFF"
    assignment["handoff_at"] = handoff_at
    assignment["handoff_lateness_seconds"] = lateness
    assignment["sla_breached"] = lateness > K.HANDOFF_GRACE_SECONDS
    assignment["handoff_penalty_cents"] = penalty
    db.touch(assignment)

    network = db.courier_networks.get(assignment["courier_network_id"])
    if network is not None:
        if penalty:
            network["penalty_accrued_cents"] += penalty
            db.touch(network)
        domain.recompute_network_open_assignments(network)

    order["fulfillment_status"] = "HANDED_OFF"
    db.touch(order)
    store = db.stores.get(order["store_id"])
    if store is not None:
        store["open_order_count"] = max(0, store["open_order_count"] - 1)
        db.touch(store)
    return response.object_response(serializers.assignment(assignment))


@bp.post("/delivery-assignments/<assignment_id>/deliver")
@M.endpoint(M.COURIER_AGENT)
def deliver_assignment(assignment_id):
    assignment = common.get_assignment(assignment_id)
    order = _scope(assignment)

    if assignment["state"] != "HANDED_OFF":
        fail(errors.ERR_INVALID_ASSIGNMENT_STATE)

    assignment["state"] = "DELIVERED"
    assignment["delivered_at"] = clock.now()
    db.touch(assignment)

    if order is not None and order["fulfillment_status"] == "HANDED_OFF":
        order["fulfillment_status"] = "DELIVERED"
        db.touch(order)
    return response.object_response(serializers.assignment(assignment))
