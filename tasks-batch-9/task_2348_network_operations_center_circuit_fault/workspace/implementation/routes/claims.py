"""SLA credit claims and the carrier's open exposure ledger (PRD 3.6)."""

from flask import Blueprint, g

import db
import derive
import lookup
from consts import CLAIM_BASES, CLAIM_ORIGINS, CLAIM_STATES
from db import now, rows, touch
from errors import fail
from middleware import authenticate, liaison_carrier_id, require_carrier_scope, scope_read
from routes._common import body_ref, send, send_list
from valid import body, opt_enum, opt_string, q_enum, q_string, req_enum, req_int

bp = Blueprint("claims", __name__)

MANAGER_ROLES = ("VendorManager", "PlatformAdmin")
READ_ROLES = ("NocShiftLead", "CarrierLiaison", "VendorManager", "PlatformAdmin")
CARRIER_ROLES = ("CarrierLiaison", "PlatformAdmin")

BLOCKING_CLAIM_STATES = ("DRAFT", "SUBMITTED", "ACKNOWLEDGED", "PAID")
RESPONSES = ("ACKNOWLEDGED", "REJECTED")


def _carrier_of(claim):
    return db.db.carriers.get(claim["carrier_id"])


def _settle_ledger(claim):
    carrier = _carrier_of(claim)
    if carrier is not None:
        derive.recompute_exposure(carrier)
        touch(carrier)
    return carrier


@bp.post("/sla-credit-claims")
def create_claim():
    authenticate(MANAGER_ROLES)
    payload = body()
    ticket = body_ref(payload, "carrier_ticket_id", lookup.ticket)
    if ticket is None:
        fail("ERR_INVALID_REQUEST", "carrier_ticket_id is required.")
    expected_version = req_int(payload, "expected_carrier_ticket_version", 0)
    basis = opt_enum(payload, "basis", CLAIM_BASES, "CARRIER_CLOCK")

    if ticket["state"] != "CLOSED_RESTORED":
        fail("ERR_TICKET_NOT_CLOSED")
    if expected_version != ticket["version"]:
        fail("ERR_STALE_CARRIER_TICKET_VERSION")
    for existing in db.db.claims.values():
        if (
            existing["carrier_ticket_id"] == ticket["id"]
            and existing["state"] in BLOCKING_CLAIM_STATES
        ):
            fail("ERR_CLAIM_ALREADY_OPEN")

    figures = derive.credit_figures(ticket, basis)
    if figures["credit_amount_cents"] <= 0:
        fail("ERR_NO_SLA_BREACH")

    claim = derive.build_claim(ticket, basis, "MANUAL")
    touch(ticket)
    _settle_ledger(claim)
    return send(claim, 201)


@bp.get("/sla-credit-claims/<id>")
def get_claim(id):
    authenticate(READ_ROLES)
    claim = lookup.claim(id)
    scope_read(claim["carrier_id"])
    return send(claim)


@bp.get("/sla-credit-claims")
def list_claims():
    authenticate(READ_ROLES)
    carrier_ticket_id = q_string("carrier_ticket_id")
    carrier_id = q_string("carrier_id") or liaison_carrier_id()
    state = q_enum("state", CLAIM_STATES)
    basis = q_enum("basis", CLAIM_BASES)
    origin = q_enum("origin", CLAIM_ORIGINS)
    result = []
    for claim in rows(db.db.claims):
        if carrier_ticket_id and claim["carrier_ticket_id"] != carrier_ticket_id:
            continue
        if carrier_id and claim["carrier_id"] != carrier_id:
            continue
        if state and claim["state"] != state:
            continue
        if basis and claim["basis"] != basis:
            continue
        if origin and claim["origin"] != origin:
            continue
        result.append(claim)
    return send_list(result)


@bp.post("/sla-credit-claims/<id>/submit")
def submit_claim(id):
    authenticate(MANAGER_ROLES)
    claim = lookup.claim(id)
    payload = body()
    basis = opt_enum(payload, "basis", CLAIM_BASES)
    opt_string(payload, "attestation_note")

    if claim["state"] not in ("DRAFT", "REJECTED"):
        fail("ERR_CLAIM_STATE_INVALID")

    ticket = db.db.tickets.get(claim["carrier_ticket_id"])
    if ticket is None or ticket["state"] != "CLOSED_RESTORED":
        fail("ERR_TICKET_NOT_CLOSED")

    incident = db.db.incidents.get(ticket["incident_id"])
    if incident is None or incident["response_state"] not in ("MITIGATED", "RESOLVED"):
        fail("ERR_INCIDENT_NOT_MITIGATED")

    if g.user_id == ticket["restoration_confirmed_by_user_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES")

    effective_basis = basis or claim["basis"]
    figures = derive.credit_figures(ticket, effective_basis)
    amount = figures["credit_amount_cents"]
    if amount <= 0:
        fail("ERR_NO_SLA_BREACH")

    carrier = _carrier_of(claim)
    minimum = carrier["min_claim_amount_cents"] if carrier else 0
    if amount < minimum:
        fail("ERR_CLAIM_BELOW_MINIMUM")

    if basis is not None:
        derive.apply_credit_figures(claim, ticket, basis)

    if claim["state"] == "REJECTED":
        claim["revision_count"] = claim["revision_count"] + 1
        claim["rejection_reason"] = None
    claim["state"] = "SUBMITTED"
    claim["submitted_by_user_id"] = g.user_id
    claim["submitted_at"] = now()
    touch(claim)
    _settle_ledger(claim)
    return send(claim)


@bp.post("/sla-credit-claims/<id>/carrier-response")
def respond_to_claim(id):
    authenticate(CARRIER_ROLES)
    claim = lookup.claim(id)
    require_carrier_scope(claim["carrier_id"])
    payload = body()
    response = req_enum(payload, "response", RESPONSES)
    rejection_reason = opt_string(payload, "rejection_reason")

    if response == "REJECTED" and not (rejection_reason or "").strip():
        fail("ERR_INVALID_REQUEST", "rejection_reason is required for a rejection.")
    if claim["state"] != "SUBMITTED":
        fail("ERR_CLAIM_STATE_INVALID")

    if response == "ACKNOWLEDGED":
        claim["state"] = "ACKNOWLEDGED"
    else:
        claim["rejection_reason"] = rejection_reason
        claim["state"] = "REJECTED"
    touch(claim)
    _settle_ledger(claim)
    return send(claim)


@bp.post("/sla-credit-claims/<id>/settle")
def settle_claim(id):
    authenticate(MANAGER_ROLES)
    claim = lookup.claim(id)
    payload = body()
    paid_amount_cents = req_int(payload, "paid_amount_cents")

    if claim["state"] != "ACKNOWLEDGED":
        fail("ERR_CLAIM_STATE_INVALID")
    if paid_amount_cents != claim["credit_amount_cents"]:
        fail("ERR_CREDIT_AMOUNT_MISMATCH")

    claim["paid_amount_cents"] = paid_amount_cents
    claim["state"] = "PAID"
    touch(claim)
    _settle_ledger(claim)
    return send(claim)


@bp.post("/sla-credit-claims/<id>/withdraw")
def withdraw_claim(id):
    authenticate(MANAGER_ROLES)
    claim = lookup.claim(id)
    body()

    if claim["state"] not in ("DRAFT", "SUBMITTED", "REJECTED"):
        fail("ERR_CLAIM_STATE_INVALID")

    claim["state"] = "WITHDRAWN"
    touch(claim)
    _settle_ledger(claim)
    return send(claim)
