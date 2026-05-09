"""Manual review case routes."""

from __future__ import annotations

from flask import Blueprint, jsonify

from db import db
from errors import (
    ERR_INVALID_STATE,
    ERR_NOT_FOUND,
    ERR_POLICY_INACTIVE,
    raise_api_error,
)
from middleware import require_roles
from response import success_response
from services.common import (
    append_audit,
    check_version,
    get_case_or_404,
    get_insurer_or_404,
    get_json_body,
    get_policy_or_404,
    require_field,
)

bp = Blueprint("manual_review", __name__)


def _serialize_case(c: dict) -> dict:
    return dict(c)


def _claims_referencing_ticket(ticket_id: str) -> list[dict]:
    return [c for c in db.claims.values() if ticket_id in (c.get("ticket_ids") or [])]


@bp.get("/insurers/<insurer_id>/manual_review/<case_id>")
@require_roles("ClaimsReviewer", "ClaimsAdmin")
def get_case(insurer_id: str, case_id: str):
    get_insurer_or_404(insurer_id)
    case = get_case_or_404(insurer_id, case_id)
    return jsonify(success_response(_serialize_case(case))), 200


@bp.post("/insurers/<insurer_id>/manual_review/<case_id>/resolve_bind")
@require_roles("ClaimsReviewer")
def resolve_bind(insurer_id: str, case_id: str):
    get_insurer_or_404(insurer_id)
    case = get_case_or_404(insurer_id, case_id)
    body = get_json_body()
    check_version(body, case)

    if case["status"] != "OPEN":
        raise_api_error(ERR_INVALID_STATE, f"Case is in status {case['status']}.")

    resolved_policy_id = require_field(body, "resolved_policy_id", type_=str)
    pol = get_policy_or_404(insurer_id, resolved_policy_id)
    if pol["status"] != "ACTIVE":
        raise_api_error(ERR_POLICY_INACTIVE, "Resolved policy is not ACTIVE.")

    ticket = db.tickets.get(case["ticket_id"])
    if not ticket:
        raise_api_error(ERR_NOT_FOUND, "Underlying ticket not found.")
    if ticket["status"] not in ("ATTACHED", "CHANGED", "UNMATCHED"):
        raise_api_error(ERR_INVALID_STATE, f"Ticket in status {ticket['status']} cannot be bound.")

    ticket["policy_id"] = resolved_policy_id
    if ticket["status"] == "UNMATCHED":
        ticket["status"] = "ATTACHED"
    db.stamp_update(ticket)

    case["status"] = "RESOLVED_BIND"
    case["resolved_policy_id"] = resolved_policy_id
    from flask import g
    case["assigned_reviewer_id"] = g.user_id
    db.stamp_update(case)

    # Cascade: pending claims referencing this ticket → MATCHED
    for c in _claims_referencing_ticket(ticket["id"]):
        if c.get("review_status") == "PENDING_MATCH":
            c["review_status"] = "MATCHED"
            db.stamp_update(c)
            append_audit(insurer_id, "CLAIM", c["id"], "STATUS_CHANGE",
                         {"from": "PENDING_MATCH", "to": "MATCHED",
                          "cascade": "manual_review_bind"})

    return jsonify(success_response(_serialize_case(case))), 200


@bp.post("/insurers/<insurer_id>/manual_review/<case_id>/resolve_reject")
@require_roles("ClaimsReviewer")
def resolve_reject(insurer_id: str, case_id: str):
    get_insurer_or_404(insurer_id)
    case = get_case_or_404(insurer_id, case_id)
    body = get_json_body()
    check_version(body, case)

    if case["status"] != "OPEN":
        raise_api_error(ERR_INVALID_STATE, f"Case is in status {case['status']}.")

    ticket = db.tickets.get(case["ticket_id"])
    if ticket:
        ticket["status"] = "UNMATCHED"
        db.stamp_update(ticket)

    case["status"] = "RESOLVED_REJECT"
    from flask import g
    case["assigned_reviewer_id"] = g.user_id
    db.stamp_update(case)

    if ticket:
        for c in _claims_referencing_ticket(ticket["id"]):
            if c.get("review_status") in ("PENDING_MATCH", "MATCHED"):
                c["review_status"] = "REJECTED"
                c["rejection_reason"] = "MATCHING_FAILED"
                db.stamp_update(c)
                append_audit(insurer_id, "CLAIM", c["id"], "STATUS_CHANGE",
                             {"to": "REJECTED", "rejection_reason": "MATCHING_FAILED",
                              "cascade": "manual_review_reject"})

    return jsonify(success_response(_serialize_case(case))), 200
