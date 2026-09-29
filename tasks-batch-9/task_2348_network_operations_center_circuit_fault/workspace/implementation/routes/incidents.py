"""Incident reads and the two parallel lifecycle dimensions (PRD 3.4)."""

from flask import Blueprint

import db
import derive
import lookup
from consts import ESCALATION_STATES, RESPONSE_STATES, SEVERITIES
from db import now, rows, touch
from errors import fail
from middleware import authenticate
from routes._common import send, send_list
from valid import body, opt_string, q_enum, q_string, req_enum

bp = Blueprint("incidents", __name__)

READ_ROLES = ("NocAnalyst", "NocShiftLead", "VendorManager", "PlatformAdmin")
RESPONSE_ROLES = ("NocAnalyst", "NocShiftLead", "PlatformAdmin")
LEAD_ROLES = ("NocShiftLead", "PlatformAdmin")

RESPONSE_STEPS = {"DETECTED": "TRIAGED", "TRIAGED": "MITIGATED"}
ESCALATION_STEPS = {"NONE": "L1", "L1": "L2", "L2": "EXEC"}
DEESCALATION = {"EXEC": "L2", "L2": "L1"}

TERMINAL_TICKET_STATES = ("CLOSED_RESTORED", "CLOSED_NO_FAULT")


@bp.get("/incidents/<id>")
def get_incident(id):
    authenticate(READ_ROLES)
    return send(lookup.incident(id))


@bp.get("/incidents")
def list_incidents():
    authenticate(READ_ROLES)
    primary_circuit_id = q_string("primary_circuit_id")
    root_alarm_id = q_string("root_alarm_id")
    severity = q_enum("severity", SEVERITIES)
    response_state = q_enum("response_state", RESPONSE_STATES)
    escalation_state = q_enum("escalation_state", ESCALATION_STATES)
    result = []
    for incident in rows(db.db.incidents):
        if primary_circuit_id and incident["primary_circuit_id"] != primary_circuit_id:
            continue
        if root_alarm_id and incident["root_alarm_id"] != root_alarm_id:
            continue
        if severity and incident["severity"] != severity:
            continue
        if response_state and incident["response_state"] != response_state:
            continue
        if escalation_state and incident["escalation_state"] != escalation_state:
            continue
        result.append(incident)
    return send_list(result)


@bp.post("/incidents/<id>/response")
def advance_response(id):
    authenticate(RESPONSE_ROLES)
    incident = lookup.incident(id)
    payload = body()
    target = req_enum(payload, "target_response_state", RESPONSE_STATES)
    opt_string(payload, "note")

    if RESPONSE_STEPS.get(incident["response_state"]) != target:
        fail("ERR_RESPONSE_SEQUENCE_INVALID")

    instant = now()
    incident["response_state"] = target
    if target == "TRIAGED":
        incident["triaged_at"] = instant
    else:
        incident["mitigated_at"] = instant
        current = incident["escalation_state"]
        if current in DEESCALATION:
            incident["escalation_state"] = DEESCALATION[current]
    touch(incident)
    return send(incident)


@bp.post("/incidents/<id>/escalate")
def escalate_incident(id):
    authenticate(LEAD_ROLES)
    incident = lookup.incident(id)
    payload = body()
    target = req_enum(payload, "target_escalation_state", ESCALATION_STATES)

    if incident["response_state"] == "RESOLVED":
        fail("ERR_INCIDENT_ALREADY_RESOLVED")
    current = incident["escalation_state"]
    if ESCALATION_STEPS.get(current) != target:
        fail("ERR_ESCALATION_SEQUENCE_INVALID")
    if target == "EXEC" and incident["severity"] not in ("SEV1", "SEV2"):
        fail("ERR_EXEC_ESCALATION_NOT_ALLOWED")
    if target == "L2":
        due = incident["escalation_due_at"]
        if due is not None and now() < due:
            fail("ERR_ESCALATION_PREMATURE")

    incident["escalation_state"] = target
    touch(incident)
    return send(incident)


@bp.post("/incidents/<id>/resolve")
def resolve_incident(id):
    authenticate(LEAD_ROLES)
    incident = lookup.incident(id)
    payload = body()
    opt_string(payload, "resolution_note")

    if incident["response_state"] != "MITIGATED":
        fail("ERR_RESPONSE_SEQUENCE_INVALID")

    for alarm in db.db.alarms.values():
        if alarm["incident_id"] == incident["id"] and alarm["cleared_at"] is None:
            fail("ERR_OPEN_ALARMS_PRESENT")

    for ticket in db.db.tickets.values():
        if (
            ticket["incident_id"] == incident["id"]
            and ticket["state"] not in TERMINAL_TICKET_STATES
        ):
            fail("ERR_CARRIER_TICKET_OPEN")

    incident["response_state"] = "RESOLVED"
    incident["resolved_at"] = now()
    incident["escalation_state"] = "NONE"
    touch(incident)

    circuit = db.db.circuits.get(incident["primary_circuit_id"])
    if circuit is not None:
        derive.recompute_chronic(circuit)
        touch(circuit)
        carrier = db.db.carriers.get(circuit["carrier_id"])
        if carrier is not None:
            derive.recompute_chronic_circuit_count(carrier)
            touch(carrier)
    return send(incident)
