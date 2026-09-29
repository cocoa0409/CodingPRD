"""Carrier trouble tickets: evidence, tier escalation, restoration (PRD 3.5)."""

from flask import Blueprint, g

import db
import derive
import lookup
from consts import SOAK_MINUTES, TEST_OUTCOMES, TEST_TYPES, TICKET_STATES
from db import base_record, now, rows, touch
from errors import fail
from middleware import authenticate, liaison_carrier_id, require_carrier_scope, scope_read
from routes._common import body_ref, send, send_list
from timeutil import minutes_between
from valid import (
    body,
    opt_string,
    opt_ts,
    q_enum,
    q_int,
    q_string,
    req_bool,
    req_enum,
    req_int,
    req_string,
)

bp = Blueprint("tickets", __name__)

OPEN_ROLES = ("NocAnalyst", "NocShiftLead", "PlatformAdmin")
READ_ROLES = (
    "NocAnalyst",
    "NocShiftLead",
    "CarrierLiaison",
    "VendorManager",
    "PlatformAdmin",
)
LEAD_ROLES = ("NocShiftLead", "PlatformAdmin")
CARRIER_ROLES = ("CarrierLiaison", "PlatformAdmin")

CLOSED_STATES = ("CLOSED_RESTORED", "CLOSED_NO_FAULT")
TESTABLE_STATES = ("OPEN", "REOPENED", "TESTING", "ESCALATED_T2", "ESCALATED_T3")
RESTORABLE_STATES = ("OPEN", "TESTING", "ESCALATED_T2", "ESCALATED_T3", "REOPENED")
NO_FAULT_STATES = ("OPEN", "TESTING")
UPDATE_KINDS = ("RESTORED", "NO_FAULT_FOUND")


@bp.post("/carrier-tickets")
def create_ticket():
    authenticate(OPEN_ROLES)
    payload = body()
    incident = body_ref(payload, "incident_id", lookup.incident)
    circuit = body_ref(payload, "circuit_id", lookup.circuit)
    if incident is None:
        fail("ERR_INVALID_REQUEST", "incident_id is required.")
    if circuit is None:
        fail("ERR_INVALID_REQUEST", "circuit_id is required.")
    carrier_reference = req_string(payload, "carrier_reference")

    if circuit["id"] != incident["primary_circuit_id"]:
        fail("ERR_CIRCUIT_INCIDENT_MISMATCH")

    for existing in db.db.tickets.values():
        if (
            existing["carrier_id"] == circuit["carrier_id"]
            and existing["carrier_reference"] == carrier_reference
        ):
            fail("ERR_CARRIER_REFERENCE_DUPLICATE")

    for existing in db.db.tickets.values():
        if existing["circuit_id"] == circuit["id"] and existing["state"] not in CLOSED_STATES:
            fail("ERR_DUPLICATE_OPEN_TICKET")

    if circuit["monitoring_state"] != "MONITORED":
        fail("ERR_CIRCUIT_NOT_MONITORED")
    if circuit["operational_state"] not in ("DEGRADED", "DOWN"):
        fail("ERR_CIRCUIT_NOT_FAULTED")

    instant = now()
    ticket = base_record()
    ticket.update(
        {
            "incident_id": incident["id"],
            "circuit_id": circuit["id"],
            "carrier_id": circuit["carrier_id"],
            "carrier_reference": carrier_reference,
            "reported_circuit_identifier": circuit["carrier_circuit_identifier"],
            "state": "OPEN",
            "tier_level": 1,
            "tier_entered_at": instant,
            "opened_at": instant,
            "restored_at": None,
            "confirmed_at": None,
            "opened_by_user_id": g.user_id,
            "restoration_confirmed_by_user_id": None,
            "excluded_minutes": 0,
            "restoration_minutes_carrier_clock": None,
            "restoration_minutes_noc_clock": None,
            "reopen_count": 0,
            "fail_test_count": 0,
        }
    )
    db.db.tickets[ticket["id"]] = ticket
    touch(incident)
    return send(ticket, 201)


@bp.get("/carrier-tickets/<id>")
def get_ticket(id):
    authenticate(READ_ROLES)
    ticket = lookup.ticket(id)
    scope_read(ticket["carrier_id"])
    return send(ticket)


@bp.get("/carrier-tickets")
def list_tickets():
    authenticate(READ_ROLES)
    incident_id = q_string("incident_id")
    circuit_id = q_string("circuit_id")
    carrier_id = q_string("carrier_id") or liaison_carrier_id()
    state = q_enum("state", TICKET_STATES)
    tier_level = q_int("tier_level")
    result = []
    for ticket in rows(db.db.tickets):
        if incident_id and ticket["incident_id"] != incident_id:
            continue
        if circuit_id and ticket["circuit_id"] != circuit_id:
            continue
        if carrier_id and ticket["carrier_id"] != carrier_id:
            continue
        if state and ticket["state"] != state:
            continue
        if tier_level is not None and ticket["tier_level"] != tier_level:
            continue
        result.append(ticket)
    return send_list(result)


@bp.post("/carrier-tickets/<id>/test-results")
def record_test_result(id):
    authenticate(OPEN_ROLES)
    ticket = lookup.ticket(id)
    payload = body()
    test_type = req_enum(payload, "test_type", TEST_TYPES)
    outcome = req_enum(payload, "outcome", TEST_OUTCOMES)
    notes = opt_string(payload, "notes")

    if ticket["state"] not in TESTABLE_STATES:
        fail("ERR_TICKET_STATE_INVALID")

    result = base_record(versioned=False)
    result.update(
        {
            "carrier_ticket_id": ticket["id"],
            "test_type": test_type,
            "outcome": outcome,
            "notes": notes,
            "performed_at": now(),
            "recorded_by_user_id": g.user_id,
        }
    )
    db.db.test_results[result["id"]] = result

    if ticket["state"] in ("OPEN", "REOPENED"):
        ticket["state"] = "TESTING"
    if outcome in ("FAIL", "INCONCLUSIVE"):
        ticket["fail_test_count"] = ticket["fail_test_count"] + 1
    touch(ticket)
    return send(result, 201)


@bp.get("/carrier-tickets/<id>/test-results")
def list_test_results(id):
    authenticate(READ_ROLES)
    ticket = lookup.ticket(id)
    scope_read(ticket["carrier_id"])
    outcome = q_enum("outcome", TEST_OUTCOMES)
    test_type = q_enum("test_type", TEST_TYPES)
    result = [
        row
        for row in rows(db.db.test_results)
        if row["carrier_ticket_id"] == ticket["id"]
        and (outcome is None or row["outcome"] == outcome)
        and (test_type is None or row["test_type"] == test_type)
    ]
    return send_list(result)


@bp.post("/carrier-tickets/<id>/escalate")
def escalate_ticket(id):
    authenticate(LEAD_ROLES)
    ticket = lookup.ticket(id)
    payload = body()
    target_tier = req_int(payload, "target_tier", 1)
    opt_string(payload, "justification")

    if ticket["state"] not in ("TESTING", "ESCALATED_T2"):
        fail("ERR_TICKET_STATE_INVALID")
    if target_tier != ticket["tier_level"] + 1:
        fail("ERR_TIER_SEQUENCE_INVALID")

    carrier = db.db.carriers.get(ticket["carrier_id"])
    ceiling = carrier["escalation_tier_count"] if carrier else 1
    if target_tier > ceiling:
        fail("ERR_TIER_CEILING_REACHED")
    if ticket["fail_test_count"] < 1:
        fail("ERR_TEST_EVIDENCE_MISSING")

    dwell_required = carrier["tier_escalation_min_minutes"] if carrier else 0
    elapsed = minutes_between(ticket["tier_entered_at"], now())
    if elapsed < dwell_required:
        fail("ERR_TIER_DWELL_NOT_MET")

    instant = now()
    ticket["tier_level"] = target_tier
    ticket["state"] = "ESCALATED_T2" if target_tier == 2 else "ESCALATED_T3"
    ticket["tier_entered_at"] = instant
    touch(ticket)
    return send(ticket)


@bp.post("/carrier-tickets/<id>/carrier-update")
def carrier_update(id):
    authenticate(CARRIER_ROLES)
    ticket = lookup.ticket(id)
    require_carrier_scope(ticket["carrier_id"])
    payload = body()
    update = req_enum(payload, "update", UPDATE_KINDS)
    restored_at = opt_ts(payload, "restored_at")

    if update == "RESTORED":
        if restored_at is None:
            fail("ERR_INVALID_REQUEST", "restored_at is required for a RESTORED update.")
        if restored_at <= ticket["opened_at"] or restored_at > now():
            fail("ERR_TIMESTAMP_RANGE_INVALID")
        if ticket["state"] not in RESTORABLE_STATES:
            fail("ERR_TICKET_STATE_INVALID")

        noc, carrier_clock, excluded = derive.restoration_clocks(ticket, restored_at)
        ticket["restored_at"] = restored_at
        ticket["state"] = "RESTORED_PENDING_CONFIRM"
        ticket["excluded_minutes"] = excluded
        ticket["restoration_minutes_carrier_clock"] = carrier_clock
        ticket["restoration_minutes_noc_clock"] = noc
        touch(ticket)
        return send(ticket)

    if ticket["state"] not in NO_FAULT_STATES:
        fail("ERR_TICKET_STATE_INVALID")
    if ticket["fail_test_count"] > 0:
        fail("ERR_TEST_EVIDENCE_CONTRADICTS_NO_FAULT")
    ticket["state"] = "CLOSED_NO_FAULT"
    touch(ticket)
    return send(ticket)


@bp.post("/carrier-tickets/<id>/confirm-restoration")
def confirm_restoration(id):
    authenticate(LEAD_ROLES)
    ticket = lookup.ticket(id)
    payload = body()
    soak_passed = req_bool(payload, "soak_passed")

    if ticket["state"] != "RESTORED_PENDING_CONFIRM":
        fail("ERR_TICKET_STATE_INVALID")

    if not soak_passed:
        ticket["state"] = "REOPENED"
        ticket["reopen_count"] = ticket["reopen_count"] + 1
        ticket["restored_at"] = None
        ticket["excluded_minutes"] = 0
        ticket["restoration_minutes_carrier_clock"] = None
        ticket["restoration_minutes_noc_clock"] = None
        touch(ticket)
        return send(ticket)

    if derive.uncleared_root_alarms_for_circuit(ticket["circuit_id"]):
        fail("ERR_OPEN_ALARMS_PRESENT")
    if minutes_between(ticket["restored_at"], now()) < SOAK_MINUTES:
        fail("ERR_SOAK_WINDOW_NOT_ELAPSED")

    ticket["state"] = "CLOSED_RESTORED"
    ticket["confirmed_at"] = now()
    ticket["restoration_confirmed_by_user_id"] = g.user_id
    touch(ticket)

    figures = derive.credit_figures(ticket, "CARRIER_CLOCK")
    if figures["credit_amount_cents"] > 0:
        derive.build_claim(ticket, "CARRIER_CLOCK", "AUTO_DRAFT")
        carrier = db.db.carriers.get(ticket["carrier_id"])
        if carrier is not None:
            derive.recompute_exposure(carrier)
            touch(carrier)
    return send(ticket)
