"""Maintenance windows: proposal, review and execution (PRD 3.7)."""

from flask import Blueprint, g

import db
import derive
import lookup
from consts import CHANGE_BUFFER_MINUTES, WINDOW_ORIGINS, WINDOW_STATES
from db import base_record, now, rows, touch
from errors import fail
from middleware import authenticate, liaison_carrier_id, require_carrier_scope, scope_read
from routes._common import body_ref, send, send_list
from timeutil import add_minutes
from valid import body, opt_bool, q_enum, q_string, req_enum, req_ts

bp = Blueprint("windows", __name__)

CREATE_ROLES = ("NocAnalyst", "NocShiftLead", "CarrierLiaison", "PlatformAdmin")
READ_ROLES = (
    "NocAnalyst",
    "NocShiftLead",
    "CarrierLiaison",
    "VendorManager",
    "PlatformAdmin",
)
LEAD_ROLES = ("NocShiftLead", "PlatformAdmin")

DECISIONS = ("APPROVED", "REJECTED")
TARGET_STATES = ("IN_PROGRESS", "COMPLETED", "CANCELLED")
BLOCKING_WINDOW_STATES = ("APPROVED", "IN_PROGRESS")


def _projected_healthy_legs(path, circuit_id):
    """Legs that stay healthy once `circuit_id` is taken out for maintenance."""
    segments = derive.active_segments(path["id"])
    healthy = 0
    for leg in derive.leg_groups_present(segments):
        leg_segments = [s for s in segments if s["leg_group"] == leg]
        if any(s.get("circuit_id") == circuit_id for s in leg_segments):
            continue
        if all(derive.segment_target_up(s) for s in leg_segments):
            healthy += 1
    return healthy


@bp.post("/maintenance-windows")
def create_window():
    authenticate(CREATE_ROLES)
    payload = body()
    circuit = body_ref(payload, "circuit_id", lookup.circuit)
    if circuit is None:
        fail("ERR_INVALID_REQUEST", "circuit_id is required.")
    origin = req_enum(payload, "origin", WINDOW_ORIGINS)
    if origin == "CARRIER_NOTIFIED":
        require_carrier_scope(circuit["carrier_id"])
    window_start = req_ts(payload, "window_start")
    window_end = req_ts(payload, "window_end")
    suppresses_monitoring = opt_bool(payload, "suppresses_monitoring", True)

    if not window_end > window_start:
        fail("ERR_TIMESTAMP_RANGE_INVALID")

    window = base_record()
    window.update(
        {
            "circuit_id": circuit["id"],
            "carrier_id": circuit["carrier_id"],
            "origin": origin,
            "window_start": window_start,
            "window_end": window_end,
            "state": "PROPOSED",
            "suppresses_monitoring": suppresses_monitoring,
            "risk_acknowledged": False,
            "approved_by_user_id": None,
            "monitoring_state_before_start": None,
        }
    )
    db.db.windows[window["id"]] = window
    return send(window, 201)


@bp.get("/maintenance-windows/<id>")
def get_window(id):
    authenticate(READ_ROLES)
    window = lookup.window(id)
    scope_read(window["carrier_id"])
    return send(window)


@bp.get("/maintenance-windows")
def list_windows():
    authenticate(READ_ROLES)
    circuit_id = q_string("circuit_id")
    carrier_id = q_string("carrier_id") or liaison_carrier_id()
    state = q_enum("state", WINDOW_STATES)
    origin = q_enum("origin", WINDOW_ORIGINS)
    result = []
    for window in rows(db.db.windows):
        if circuit_id and window["circuit_id"] != circuit_id:
            continue
        if carrier_id and window["carrier_id"] != carrier_id:
            continue
        if state and window["state"] != state:
            continue
        if origin and window["origin"] != origin:
            continue
        result.append(window)
    return send_list(result)


@bp.post("/maintenance-windows/<id>/review")
def review_window(id):
    authenticate(LEAD_ROLES)
    window = lookup.window(id)
    require_carrier_scope(window["carrier_id"])
    payload = body()
    decision = req_enum(payload, "decision", DECISIONS)
    risk_acknowledged = opt_bool(payload, "risk_acknowledged", False)

    if window["state"] != "PROPOSED":
        fail("ERR_WINDOW_STATE_INVALID")

    if decision == "REJECTED":
        window["state"] = "REJECTED"
        window["approved_by_user_id"] = g.user_id
        touch(window)
        return send(window)

    circuit_id = window["circuit_id"]
    for path in derive.affected_paths(circuit_id):
        projected = _projected_healthy_legs(path, circuit_id)
        if projected <= path["min_surviving_legs"] and not risk_acknowledged:
            fail("ERR_REDUNDANCY_RISK_UNACKNOWLEDGED")

    buffer_minutes = CHANGE_BUFFER_MINUTES
    for other in rows(db.db.windows):
        if other["id"] == window["id"]:
            continue
        if other["circuit_id"] != circuit_id:
            continue
        if other["state"] not in BLOCKING_WINDOW_STATES:
            continue
        if window["window_start"] < add_minutes(other["window_end"], buffer_minutes) and other[
            "window_start"
        ] < add_minutes(window["window_end"], buffer_minutes):
            fail("ERR_WINDOW_OVERLAP")

    window["state"] = "APPROVED"
    window["risk_acknowledged"] = risk_acknowledged
    window["approved_by_user_id"] = g.user_id
    touch(window)
    return send(window)


@bp.post("/maintenance-windows/<id>/state")
def change_window_state(id):
    authenticate(LEAD_ROLES)
    window = lookup.window(id)
    payload = body()
    target_state = req_enum(payload, "target_state", WINDOW_STATES)

    if target_state not in TARGET_STATES:
        fail("ERR_WINDOW_STATE_INVALID")

    circuit = db.db.circuits.get(window["circuit_id"])

    if target_state == "IN_PROGRESS":
        if window["state"] != "APPROVED":
            fail("ERR_WINDOW_STATE_INVALID")
        instant = now()
        if instant < window["window_start"] or instant >= window["window_end"]:
            fail("ERR_WINDOW_NOT_IN_EFFECT")
        if circuit is not None:
            window["monitoring_state_before_start"] = circuit["monitoring_state"]
            if window["suppresses_monitoring"]:
                circuit["monitoring_state"] = "MAINTENANCE_SUPPRESSED"
            touch(circuit)
        window["state"] = "IN_PROGRESS"
        touch(window)
        derive.recompute_topology()
        return send(window)

    if target_state == "COMPLETED":
        if window["state"] != "IN_PROGRESS":
            fail("ERR_WINDOW_STATE_INVALID")
        if circuit is not None:
            if window["monitoring_state_before_start"] is not None:
                circuit["monitoring_state"] = window["monitoring_state_before_start"]
            touch(circuit)
        window["state"] = "COMPLETED"
        touch(window)
        derive.recompute_topology()
        return send(window)

    if window["state"] not in ("PROPOSED", "APPROVED"):
        fail("ERR_WINDOW_STATE_INVALID")
    if (
        circuit is not None
        and window["monitoring_state_before_start"] is not None
        and circuit["monitoring_state"] == "MAINTENANCE_SUPPRESSED"
    ):
        circuit["monitoring_state"] = window["monitoring_state_before_start"]
        touch(circuit)
    window["state"] = "CANCELLED"
    touch(window)
    derive.recompute_topology()
    return send(window)
