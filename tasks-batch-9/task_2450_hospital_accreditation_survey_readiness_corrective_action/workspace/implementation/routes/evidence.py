"""The evidence repository: filing, independent review and expiry (PRD 3.2)."""

from flask import Blueprint, g, request

import calc
import cascade
import serialize
from auth import ALL_ROLES, require_action_role, require_roles
from envelope import array_response, object_response
from errors import ApiError
from helpers import (
    body,
    get_evidence,
    get_standard,
    opt_dt,
    opt_str,
    page,
    pagination,
    req_dt,
    req_enum,
    req_str,
)
from store import base_entity, db, rows, touch

bp = Blueprint("evidence", __name__)

ACTIONS = ("SUBMIT", "VALIDATE", "REJECT")
ACTION_ROLES = {
    "SUBMIT": ("StandardOwner",),
    "VALIDATE": ("EvidenceValidator",),
    "REJECT": ("EvidenceValidator",),
}


@bp.post("/accreditation/standards/<standard_id>/evidence-items")
def file_evidence(standard_id):
    require_roles("StandardOwner")
    b = body()
    title = req_str(b, "title")
    doc_type = req_enum(b, "doc_type", calc.DOC_TYPES)
    effective_date = req_dt(b, "effective_date")
    expires_at = opt_dt(b, "expires_at")

    standard = get_standard(standard_id)

    item = base_entity("EvidenceItem")
    item.update(
        {
            "standard_id": standard["id"],
            "title": title,
            "doc_type": doc_type,
            "effective_date": effective_date,
            "expires_at": expires_at,
            "validation_state": "DRAFT",
            "submitted_by_user_id": None,
            "reviewed_by_user_id": None,
            "review_note": None,
            "rejection_count": 0,
        }
    )
    db.evidence_items[item["id"]] = item
    return object_response(serialize.evidence_item(item), 201)


@bp.get("/accreditation/standards/<standard_id>/evidence-items")
def list_evidence(standard_id):
    require_roles(*ALL_ROLES)
    limit, offset = pagination()
    standard = get_standard(standard_id)
    state_filter = request.args.get("validation_state")
    result = [e for e in rows(db.evidence_items) if e["standard_id"] == standard["id"]]
    if state_filter:
        result = [e for e in result if e["validation_state"] == state_filter]
    items, total = page(result, limit, offset)
    return array_response([serialize.evidence_item(e) for e in items], limit, offset, total)


@bp.get("/accreditation/evidence-items/<evidence_id>")
def read_evidence(evidence_id):
    require_roles(*ALL_ROLES)
    item = get_evidence(evidence_id)
    return object_response(serialize.evidence_item(item))


@bp.post("/accreditation/evidence-items/<evidence_id>/transition")
def transition_evidence(evidence_id):
    _, role = require_roles("StandardOwner", "EvidenceValidator")
    b = body()

    # Rung 2 for the specific action requested.
    require_action_role(role, b.get("action"), ACTION_ROLES)

    # Rung 3
    action = req_enum(b, "action", ACTIONS)
    review_note = opt_str(b, "review_note")

    # Rung 5
    item = get_evidence(evidence_id)
    standard = db.standards[item["standard_id"]]
    state = item["validation_state"]

    # Rung 12 — VALIDATE requires SUBMITTED, and it runs before rung 34.
    if action == "VALIDATE" and state != "SUBMITTED":
        raise ApiError("ERR_EVIDENCE_NOT_SUBMITTED")

    # Rung 13 — declared transitions.
    if action == "SUBMIT" and state not in ("DRAFT", "REJECTED"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    if action == "REJECT" and state not in ("SUBMITTED", "VALIDATED"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION")

    # Rung 34
    if action == "VALIDATE":
        expires_at = item["expires_at"]
        if expires_at is not None and expires_at <= db.clock:
            raise ApiError("ERR_EVIDENCE_EXPIRED")

    # Rung 40
    if action in ("VALIDATE", "REJECT"):
        if cascade.is_active_owner(standard["id"], g.user_id):
            raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    # Rung 42
    if action == "SUBMIT":
        if standard["compliance_state"] == "UNMAPPED" or not cascade.is_active_owner(
            standard["id"], g.user_id
        ):
            raise ApiError("ERR_STANDARD_UNMAPPED")

    if action == "SUBMIT":
        item["validation_state"] = "SUBMITTED"
        item["submitted_by_user_id"] = g.user_id
        touch(item)
    elif action == "VALIDATE":
        item["validation_state"] = "VALIDATED"
        item["reviewed_by_user_id"] = g.user_id
        item["review_note"] = review_note
        touch(item)
        cascade.on_evidence_counted(standard)
    else:
        was_validated = state == "VALIDATED"
        item["validation_state"] = "REJECTED"
        item["reviewed_by_user_id"] = g.user_id
        item["review_note"] = review_note
        item["rejection_count"] += 1
        touch(item)
        if was_validated:
            cascade.on_evidence_uncounted(standard)

    return object_response(serialize.evidence_item(item))
