"""Ticket routes (ingest, change, confirm, refund) with auto-match."""

from __future__ import annotations

from flask import Blueprint, jsonify

from db import db, gen_id, now_iso_z
from errors import (
    ERR_DUPLICATE_PNR,
    ERR_FLIGHT_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_NOT_FOUND,
    ERR_TICKET_LOCKED_BY_CLAIM,
    raise_api_error,
)
from middleware import require_roles
from response import success_response
from services.common import (
    append_audit,
    check_version,
    get_insurer_or_404,
    get_json_body,
    get_ticket_or_404,
    optional_field,
    require_field,
)

bp = Blueprint("tickets", __name__)


def _serialize_ticket(t: dict) -> dict:
    return dict(t)


def _claims_referencing_ticket(ticket_id: str) -> list[dict]:
    out = []
    for c in db.claims.values():
        if ticket_id in (c.get("ticket_ids") or []):
            out.append(c)
    return out


@bp.post("/insurers/<insurer_id>/tickets")
@require_roles("PolicyAdmin")
def create_ticket(insurer_id: str):
    get_insurer_or_404(insurer_id)
    body = get_json_body()

    passenger_name = require_field(body, "passenger_name", type_=str)
    passenger_doc_id = require_field(body, "passenger_doc_id", type_=str)
    pnr_code = require_field(body, "pnr_code", type_=str)
    flight_id = require_field(body, "flight_id", type_=str)
    explicit_policy_id = optional_field(body, "policy_id", default=None, type_=str)

    flight = db.flights.get(flight_id)
    if not flight or flight.get("insurer_id") != insurer_id:
        raise_api_error(ERR_FLIGHT_NOT_FOUND, "Referenced flight not found.")

    # PNR uniqueness when status IN {ATTACHED, CHANGED}
    for t in db.tickets.values():
        if (t.get("insurer_id") == insurer_id
            and t.get("pnr_code") == pnr_code
            and t.get("status") in ("ATTACHED", "CHANGED")):
            raise_api_error(ERR_DUPLICATE_PNR, "PNR already in use.")

    ticket = {
        "id": gen_id(),
        "policy_id": None,
        "insurer_id": insurer_id,
        "passenger_name": passenger_name,
        "passenger_doc_id": passenger_doc_id,
        "pnr_code": pnr_code,
        "flight_id": flight_id,
        "scheduled_departure_epoch_ms": flight["scheduled_departure_epoch_ms"],
        "scheduled_arrival_epoch_ms": flight["scheduled_arrival_epoch_ms"],
        "status": "ATTACHED",
    }

    matched_policy = None
    failure_reason: str | None = None
    if explicit_policy_id is not None:
        # Direct binding short-circuit
        pol = db.policies.get(explicit_policy_id)
        if not pol or pol.get("insurer_id") != insurer_id:
            raise_api_error(ERR_NOT_FOUND, "Policy not found.")
        matched_policy = pol
    else:
        candidates = [p for p in db.policies.values()
                      if p.get("insurer_id") == insurer_id
                      and p.get("policy_holder_doc_id") == passenger_doc_id
                      and p.get("status") == "ACTIVE"]
        if len(candidates) == 1:
            matched_policy = candidates[0]
        elif len(candidates) > 1:
            failure_reason = "DUPLICATE_BINDING"
        else:
            failure_reason = "NO_POLICY_FOUND"

    if matched_policy is not None:
        ticket["policy_id"] = matched_policy["id"]
        ticket["status"] = "ATTACHED"
    else:
        ticket["status"] = "UNMATCHED"

    db.stamp_create(ticket)
    db.tickets[ticket["id"]] = ticket

    if matched_policy is None and failure_reason is not None:
        # Open a manual review case
        case = {
            "id": gen_id(),
            "insurer_id": insurer_id,
            "ticket_id": ticket["id"],
            "failure_reason": failure_reason,
            "candidate_policy_ids": [],
            "status": "OPEN",
            "resolved_policy_id": None,
            "assigned_reviewer_id": None,
        }
        db.stamp_create(case)
        db.manual_review_cases[case["id"]] = case

    return jsonify(success_response(_serialize_ticket(ticket))), 201


@bp.get("/insurers/<insurer_id>/tickets/<ticket_id>")
@require_roles("Any")
def get_ticket(insurer_id: str, ticket_id: str):
    get_insurer_or_404(insurer_id)
    t = get_ticket_or_404(insurer_id, ticket_id)
    return jsonify(success_response(_serialize_ticket(t))), 200


@bp.post("/insurers/<insurer_id>/tickets/<ticket_id>/change")
@require_roles("PolicyAdmin")
def change_ticket(insurer_id: str, ticket_id: str):
    get_insurer_or_404(insurer_id)
    t = get_ticket_or_404(insurer_id, ticket_id)
    body = get_json_body()
    check_version(body, t)
    new_flight_id = require_field(body, "flight_id", type_=str)

    if t["status"] != "ATTACHED":
        raise_api_error(ERR_INVALID_STATE, f"Ticket in status {t['status']} cannot be changed.")

    new_flight = db.flights.get(new_flight_id)
    if not new_flight or new_flight.get("insurer_id") != insurer_id:
        raise_api_error(ERR_FLIGHT_NOT_FOUND, "New flight not found.")

    # Lock check: any claim referencing this ticket in (UNDER_REVIEW, APPROVED) blocks change
    for c in _claims_referencing_ticket(ticket_id):
        if c.get("review_status") in ("UNDER_REVIEW", "APPROVED"):
            raise_api_error(ERR_TICKET_LOCKED_BY_CLAIM,
                            "Ticket is locked by a claim under review or approved.")

    t["flight_id"] = new_flight_id
    t["scheduled_departure_epoch_ms"] = new_flight["scheduled_departure_epoch_ms"]
    t["scheduled_arrival_epoch_ms"] = new_flight["scheduled_arrival_epoch_ms"]
    t["status"] = "CHANGED"
    db.stamp_update(t)
    return jsonify(success_response(_serialize_ticket(t))), 200


@bp.post("/insurers/<insurer_id>/tickets/<ticket_id>/confirm")
@require_roles("PolicyAdmin")
def confirm_ticket(insurer_id: str, ticket_id: str):
    get_insurer_or_404(insurer_id)
    t = get_ticket_or_404(insurer_id, ticket_id)
    body = get_json_body()
    check_version(body, t)
    if t["status"] != "CHANGED":
        raise_api_error(ERR_INVALID_STATE, f"Ticket in status {t['status']} cannot be confirmed.")
    t["status"] = "ATTACHED"
    db.stamp_update(t)
    return jsonify(success_response(_serialize_ticket(t))), 200


@bp.post("/insurers/<insurer_id>/tickets/<ticket_id>/refund")
@require_roles("PolicyAdmin")
def refund_ticket(insurer_id: str, ticket_id: str):
    get_insurer_or_404(insurer_id)
    t = get_ticket_or_404(insurer_id, ticket_id)
    body = get_json_body()
    check_version(body, t)
    if t["status"] not in ("ATTACHED", "CHANGED"):
        raise_api_error(ERR_INVALID_STATE, f"Ticket in status {t['status']} cannot be refunded.")

    # Lock: any claim in APPROVED/EXECUTING/PAID (review or payout) blocks refund
    for c in _claims_referencing_ticket(ticket_id):
        if c.get("review_status") == "APPROVED":
            raise_api_error(ERR_TICKET_LOCKED_BY_CLAIM, "Ticket is locked by an approved claim.")
        if c.get("payout_status") in ("EXECUTING", "PAID"):
            raise_api_error(ERR_TICKET_LOCKED_BY_CLAIM, "Ticket is locked by a paying claim.")

    prev_status = t["status"]
    t["status"] = "REFUNDED"
    db.stamp_update(t)

    # Cascade: if refund happens from ATTACHED, reject early-review claims with DUPLICATE
    if prev_status == "ATTACHED":
        for c in _claims_referencing_ticket(ticket_id):
            if c.get("review_status") in ("PENDING_MATCH", "MATCHED", "UNDER_REVIEW"):
                c["review_status"] = "REJECTED"
                c["rejection_reason"] = "DUPLICATE"
                db.stamp_update(c)
                append_audit(insurer_id, "CLAIM", c["id"], "STATUS_CHANGE",
                             {"to": "REJECTED", "rejection_reason": "DUPLICATE",
                              "cascade": "ticket_refund"})

    return jsonify(success_response(_serialize_ticket(t))), 200
