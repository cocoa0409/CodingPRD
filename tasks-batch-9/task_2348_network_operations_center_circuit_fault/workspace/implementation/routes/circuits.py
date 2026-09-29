"""Circuit registration, reads and capacity telemetry (PRD 3.1, 3.8)."""

from flask import Blueprint, g

import db
import derive
import lookup
from consts import (
    ALL_ROLES,
    BANDWIDTH_LADDER_MBPS,
    DEVICE_ROLES,
    DIRECTIONS,
    MONITORING_STATES_INPUT,
    ORDER_ORIGINS,
    ORDER_STATES,
    THRESHOLD_STATES,
)
from db import base_record, now, rows, touch
from errors import fail
from middleware import authenticate, scope_read
from routes._common import body_ref, send, send_list
from valid import body, opt_enum, q_enum, req_decimal, req_enum, req_int, req_string, req_ts

bp = Blueprint("circuits", __name__)


@bp.post("/circuits")
def create_circuit():
    authenticate("PlatformAdmin")
    payload = body()
    carrier = body_ref(payload, "carrier_id", lookup.carrier)
    if carrier is None:
        fail("ERR_INVALID_REQUEST", "carrier_id is required.")
    identifier = req_string(payload, "carrier_circuit_identifier")
    site_a_code = req_string(payload, "site_a_code")
    site_z_code = req_string(payload, "site_z_code")
    bandwidth_mbps = req_int(payload, "bandwidth_mbps")
    if bandwidth_mbps not in BANDWIDTH_LADDER_MBPS:
        fail(
            "ERR_INVALID_REQUEST",
            "bandwidth_mbps must be one of %s."
            % ", ".join(str(r) for r in BANDWIDTH_LADDER_MBPS),
        )
    mrc_cents = req_int(payload, "mrc_cents", 1)
    monitoring_state = opt_enum(
        payload, "monitoring_state", MONITORING_STATES_INPUT, "UNMONITORED"
    )

    for existing in db.db.circuits.values():
        if (
            existing["carrier_id"] == carrier["id"]
            and existing["carrier_circuit_identifier"] == identifier
        ):
            fail("ERR_CIRCUIT_IDENTIFIER_DUPLICATE")

    circuit = base_record()
    circuit.update(
        {
            "carrier_id": carrier["id"],
            "carrier_circuit_identifier": identifier,
            "site_a_code": site_a_code,
            "site_z_code": site_z_code,
            "bandwidth_mbps": bandwidth_mbps,
            "mrc_cents": mrc_cents,
            "monitoring_state": monitoring_state,
            "operational_state": "UP",
            "chronic_state": "NORMAL",
            "capacity_state": "NORMAL",
            "consecutive_high_readings": 0,
            "spof_flag": False,
            "fault_count_period": 0,
            "last_incident_at": None,
        }
    )
    db.db.circuits[circuit["id"]] = circuit
    return send(circuit, 201)


@bp.get("/circuits/<id>")
def get_circuit(id):
    authenticate(ALL_ROLES)
    circuit = lookup.circuit(id)
    scope_read(circuit["carrier_id"])
    return send(circuit)


@bp.get("/circuits/<id>/devices")
def list_circuit_devices(id):
    authenticate(
        "NocAnalyst", "NocShiftLead", "VendorManager", "CapacityPlanner", "PlatformAdmin"
    )
    circuit = lookup.circuit(id)
    device_role = q_enum("device_role", DEVICE_ROLES)
    result = [
        device
        for device in rows(db.db.devices)
        if device["primary_uplink_circuit_id"] == circuit["id"]
        and (device_role is None or device["device_role"] == device_role)
    ]
    return send_list(result)


@bp.post("/circuits/<id>/capacity-readings")
def create_capacity_reading(id):
    authenticate("CapacityPlanner", "PlatformAdmin")
    circuit = lookup.circuit(id)
    payload = body()
    sample_at = req_ts(payload, "sample_at")
    utilization_pct = req_decimal(payload, "utilization_pct", 0, 100)
    direction = req_enum(payload, "direction", DIRECTIONS)

    latest = None
    for reading in rows(db.db.readings):
        if reading["circuit_id"] != circuit["id"]:
            continue
        if latest is None or reading["sample_at"] > latest["sample_at"]:
            latest = reading
    if latest is not None and sample_at <= latest["sample_at"]:
        fail("ERR_READING_OUT_OF_ORDER")

    threshold_state = derive.threshold_state_for(utilization_pct)
    reading = base_record(versioned=False)
    reading.update(
        {
            "circuit_id": circuit["id"],
            "sample_at": sample_at,
            "utilization_pct": utilization_pct,
            "direction": direction,
            "threshold_state": threshold_state,
        }
    )
    db.db.readings[reading["id"]] = reading

    previous_capacity_state = circuit["capacity_state"]
    if threshold_state == "HIGH":
        circuit["consecutive_high_readings"] = circuit["consecutive_high_readings"] + 1
    else:
        circuit["consecutive_high_readings"] = 0
    circuit["capacity_state"] = derive.capacity_state_for(circuit["consecutive_high_readings"])
    touch(circuit)

    if (
        circuit["capacity_state"] == "UPGRADE_REQUIRED"
        and previous_capacity_state != "UPGRADE_REQUIRED"
    ):
        rung = derive.next_ladder_rung(circuit["bandwidth_mbps"])
        if rung is not None:
            derive.build_order(circuit, rung, False, "AUTO_THRESHOLD", "system")
            carrier = db.db.carriers.get(circuit["carrier_id"])
            if carrier is not None:
                derive.recompute_committed_upgrade(carrier)
                touch(carrier)
    return send(reading, 201)


@bp.get("/circuits/<id>/capacity-readings")
def list_capacity_readings(id):
    authenticate(
        "NocAnalyst", "NocShiftLead", "VendorManager", "CapacityPlanner", "PlatformAdmin"
    )
    circuit = lookup.circuit(id)
    direction = q_enum("direction", DIRECTIONS)
    threshold_state = q_enum("threshold_state", THRESHOLD_STATES)
    result = [
        reading
        for reading in rows(db.db.readings)
        if reading["circuit_id"] == circuit["id"]
        and (direction is None or reading["direction"] == direction)
        and (threshold_state is None or reading["threshold_state"] == threshold_state)
    ]
    return send_list(result)


@bp.get("/circuits/<id>/upgrade-orders")
def list_circuit_orders(id):
    authenticate("NocShiftLead", "VendorManager", "CapacityPlanner", "PlatformAdmin")
    circuit = lookup.circuit(id)
    state = q_enum("state", ORDER_STATES)
    origin = q_enum("origin", ORDER_ORIGINS)
    result = [
        order
        for order in rows(db.db.orders)
        if order["circuit_id"] == circuit["id"]
        and (state is None or order["state"] == state)
        and (origin is None or order["origin"] == origin)
    ]
    return send_list(result)
