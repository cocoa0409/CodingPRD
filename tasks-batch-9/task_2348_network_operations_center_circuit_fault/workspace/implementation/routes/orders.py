"""Bandwidth upgrade orders (PRD 3.8)."""

from flask import Blueprint, g

import db
import derive
import lookup
from consts import BANDWIDTH_LADDER_MBPS, ORDER_STATES
from db import touch
from errors import fail
from middleware import authenticate
from routes._common import body_ref, send
from valid import body, opt_bool, opt_string, req_enum, req_int

bp = Blueprint("orders", __name__)

PLANNER_ROLES = ("CapacityPlanner", "PlatformAdmin")
MANAGER_ROLES = ("VendorManager", "PlatformAdmin")
CANCEL_ROLES = ("CapacityPlanner", "VendorManager", "PlatformAdmin")

CANCELLABLE_STATES = ("DRAFT", "SUBMITTED", "APPROVED")


def _circuit_and_carrier(order):
    circuit = db.db.circuits.get(order["circuit_id"])
    carrier = None
    if circuit is not None:
        carrier = db.db.carriers.get(circuit["carrier_id"])
    return circuit, carrier


def _release_ledger(carrier):
    if carrier is not None:
        derive.recompute_committed_upgrade(carrier)
        touch(carrier)


@bp.post("/upgrade-orders")
def create_order():
    authenticate(PLANNER_ROLES)
    payload = body()
    circuit = body_ref(payload, "circuit_id", lookup.circuit)
    if circuit is None:
        fail("ERR_INVALID_REQUEST", "circuit_id is required.")
    target_bandwidth_mbps = req_int(payload, "target_bandwidth_mbps", 1)
    expected_version = req_int(payload, "expected_circuit_version", 0)
    expedite = opt_bool(payload, "expedite", False)

    if circuit["chronic_state"] == "REPLACEMENT_APPROVED":
        fail("ERR_CIRCUIT_SLATED_FOR_REPLACEMENT")
    if expected_version != circuit["version"]:
        fail("ERR_STALE_CIRCUIT_VERSION")
    if (
        target_bandwidth_mbps not in BANDWIDTH_LADDER_MBPS
        or target_bandwidth_mbps <= circuit["bandwidth_mbps"]
    ):
        fail("ERR_UPGRADE_TARGET_INVALID")

    order = derive.build_order(
        circuit, target_bandwidth_mbps, expedite, "MANUAL", g.user_id
    )
    touch(circuit)
    _release_ledger(db.db.carriers.get(circuit["carrier_id"]))
    return send(order, 201)


@bp.post("/upgrade-orders/<id>/submit")
def submit_order(id):
    authenticate(PLANNER_ROLES)
    order = lookup.order(id)
    body()

    if order["state"] != "DRAFT":
        fail("ERR_ORDER_STATE_INVALID")

    circuit, _carrier = _circuit_and_carrier(order)
    if circuit is not None and circuit["chronic_state"] == "REPLACEMENT_APPROVED":
        fail("ERR_CIRCUIT_SLATED_FOR_REPLACEMENT")

    order["state"] = "SUBMITTED"
    touch(order)
    return send(order)


@bp.post("/upgrade-orders/<id>/approve")
def approve_order(id):
    authenticate(MANAGER_ROLES)
    order = lookup.order(id)
    body()

    if order["state"] != "SUBMITTED":
        fail("ERR_ORDER_STATE_INVALID")
    if g.user_id == order["created_by_user_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES")

    order["state"] = "APPROVED"
    order["approved_by_user_id"] = g.user_id
    touch(order)
    return send(order)


@bp.post("/upgrade-orders/<id>/state")
def change_order_state(id):
    authenticate(PLANNER_ROLES)
    order = lookup.order(id)
    payload = body()
    target_state = req_enum(payload, "target_state", ORDER_STATES)

    if target_state == "IN_PROGRESS":
        if order["state"] != "APPROVED":
            fail("ERR_ORDER_STATE_INVALID")
        order["state"] = "IN_PROGRESS"
        touch(order)
        return send(order)

    if target_state != "COMPLETED":
        fail("ERR_ORDER_STATE_INVALID")
    if order["state"] != "IN_PROGRESS":
        fail("ERR_ORDER_STATE_INVALID")

    circuit, carrier = _circuit_and_carrier(order)
    order["state"] = "COMPLETED"
    touch(order)
    if circuit is not None:
        circuit["bandwidth_mbps"] = order["target_bandwidth_mbps"]
        circuit["consecutive_high_readings"] = 0
        circuit["capacity_state"] = "NORMAL"
        touch(circuit)
    _release_ledger(carrier)
    return send(order)


@bp.post("/upgrade-orders/<id>/cancel")
def cancel_order(id):
    authenticate(CANCEL_ROLES)
    order = lookup.order(id)
    payload = body()
    cancel_reason = opt_string(payload, "cancel_reason")

    if order["state"] not in CANCELLABLE_STATES:
        fail("ERR_ORDER_STATE_INVALID")

    _circuit, carrier = _circuit_and_carrier(order)
    order["state"] = "CANCELLED"
    order["cancel_reason"] = cancel_reason
    touch(order)
    _release_ledger(carrier)
    return send(order)
