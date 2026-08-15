"""Complaint endpoints (PRD §3.6) with segregation of duties."""

from __future__ import annotations

from datetime import timedelta

from flask import Blueprint

import db
from errors import (
    raise_err,
    raise_body_ref_err,
    ERR_BOX_NOT_FOUND,
    ERR_BOX_NOT_PUBLIC,
    ERR_COMPLAINT_NOT_FOUND,
    ERR_FORBIDDEN_OWNERSHIP,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_SEGREGATION_OF_DUTIES,
)
from middleware import require_roles
from response import success_list, success_object
from services import domain
from services.serializers import serialize_complaint
from util import (
    apply_filters,
    get_json_body,
    optional_string,
    paginate,
    parse_pagination,
    require_enum,
    require_string,
    sort_by_created_at,
)

bp = Blueprint("complaints", __name__)

COMPLAINT_CATEGORIES = {"INAPPROPRIATE_CONTENT", "HATE_SPEECH", "COMMERCIAL_SPAM", "OTHER"}
RESOLVE_OUTCOMES = {"UPHELD", "DISMISSED"}


def _load_complaint(complaint_id: str) -> dict:
    complaint = db.complaints.get(complaint_id)
    if complaint is None:
        raise_err(ERR_COMPLAINT_NOT_FOUND, "No complaint with the given id")
    return complaint


@bp.route("/library-network/complaints", methods=["POST"])
@require_roles("Anonymous", "Steward", "Moderator", "NetworkAdmin")
def create_complaint(_user_id, _role):
    body = get_json_body()
    box_id = body.get("box_id")

    # Body referential integrity (stage 4).
    box = None
    if isinstance(box_id, str):
        box = db.boxes.get(box_id)
        if box is None:
            raise_body_ref_err(ERR_BOX_NOT_FOUND, "No box with the given id")

    # Business constraint (stage 9): only publicly visible boxes — ACTIVE or
    # SUSPENDED — may be complained about.
    if box is not None and box["charter_status"] not in ("ACTIVE", "SUSPENDED"):
        raise_err(ERR_BOX_NOT_PUBLIC, "Complaints require the box to be ACTIVE or SUSPENDED")

    # Schema (stage 11).
    box_id = require_string(body, "box_id")
    category = require_enum(body, "category", COMPLAINT_CATEGORIES)
    description = require_string(body, "description")
    target_category = optional_string(body, "target_category")
    if target_category is not None and target_category not in domain.BOOK_CATEGORIES:
        raise_err(ERR_INVALID_REQUEST, "target_category must be a book category")
    evidence_url = optional_string(body, "evidence_url")

    complaint = {
        "box_id": box_id,
        "category": category,
        "target_category": target_category,
        "description": description,
        "evidence_url": evidence_url,
        "status": "FILED",
        "triaged_by_user_id": None,
        "response_due_at": None,
        "response_text": None,
        "resolved_by_user_id": None,
        "resolution_notes": None,
        "outcome": None,
        "upheld_at": None,
        "_escalated_from": None,
    }
    db.stamp_new(complaint)
    db.complaints[complaint["id"]] = complaint
    return success_object(serialize_complaint(complaint), 201)


@bp.route("/library-network/complaints", methods=["GET"])
@require_roles("Steward", "HubCoordinator", "Moderator", "NetworkAdmin")
def list_complaints(_user_id, _role):
    limit, offset = parse_pagination()
    items = [serialize_complaint(c) for c in sort_by_created_at(list(db.complaints.values()))]
    items = apply_filters(items, ["box_id", "status", "category"])
    page, total = paginate(items, limit, offset)
    return success_list(page, limit, offset, total)


@bp.route("/library-network/complaints/<complaint_id>", methods=["GET"])
@require_roles("Steward", "HubCoordinator", "Moderator", "NetworkAdmin")
def get_complaint(complaint_id: str, _user_id, _role):
    return success_object(serialize_complaint(_load_complaint(complaint_id)))


@bp.route("/library-network/complaints/<complaint_id>/triage", methods=["POST"])
@require_roles("Moderator", "NetworkAdmin")
def triage_complaint(complaint_id: str, _user_id, _role):
    complaint = _load_complaint(complaint_id)
    if complaint["status"] != "FILED":
        raise_err(ERR_INVALID_STATE, "Complaint is not in FILED status")
    complaint["status"] = "STEWARD_RESPONSE_PENDING"
    complaint["triaged_by_user_id"] = _user_id
    complaint["response_due_at"] = db.format_iso(db.clock() + timedelta(hours=72))
    db.touch(complaint)
    return success_object(serialize_complaint(complaint))


@bp.route("/library-network/complaints/<complaint_id>/respond", methods=["POST"])
@require_roles("Steward")
def respond_complaint(complaint_id: str, _user_id, _role):
    complaint = _load_complaint(complaint_id)

    # Ownership (stage 2): the responding steward must own the complained box.
    box = db.boxes.get(complaint["box_id"])
    if box is None or box["steward_id"] != _user_id:
        raise_err(ERR_FORBIDDEN_OWNERSHIP, "Steward may only respond to complaints on their own box")

    if complaint["status"] != "STEWARD_RESPONSE_PENDING":
        raise_err(ERR_INVALID_STATE, "Complaint is not awaiting a steward response")

    response_text = require_string(get_json_body(), "response_text")
    complaint["response_text"] = response_text
    complaint["status"] = "UNDER_REVIEW"
    db.touch(complaint)
    return success_object(serialize_complaint(complaint))


@bp.route("/library-network/complaints/<complaint_id>/resolve", methods=["POST"])
@require_roles("Moderator", "NetworkAdmin")
def resolve_complaint(complaint_id: str, _user_id, _role):
    complaint = _load_complaint(complaint_id)
    body = get_json_body()

    # State precondition (stage 5).
    if complaint["status"] != "UNDER_REVIEW":
        raise_err(ERR_INVALID_STATE, "Complaint is not in UNDER_REVIEW status")

    # Segregation of duties (stage 7): resolver must differ from triager.
    if _user_id == complaint.get("triaged_by_user_id"):
        raise_err(ERR_SEGREGATION_OF_DUTIES, "Resolver must differ from the triager")

    # Schema (stage 11).
    outcome = require_enum(body, "outcome", RESOLVE_OUTCOMES)
    resolution_notes = optional_string(body, "resolution_notes")

    complaint["outcome"] = outcome
    complaint["resolved_by_user_id"] = _user_id
    if resolution_notes is not None:
        complaint["resolution_notes"] = resolution_notes

    if outcome == "UPHELD":
        complaint["status"] = "RESOLVED_UPHELD"
        complaint["upheld_at"] = db.now_logical_iso()
        db.touch(complaint)
        domain.complaint_upheld_cascade(complaint)
    else:
        complaint["status"] = "RESOLVED_DISMISSED"
        db.touch(complaint)
    return success_object(serialize_complaint(complaint))


@bp.route("/library-network/complaints/<complaint_id>/escalate", methods=["POST"])
@require_roles("NetworkAdmin")
def escalate_complaint(complaint_id: str, _user_id, _role):
    complaint = _load_complaint(complaint_id)
    if complaint["status"] not in ("RESOLVED_DISMISSED", "RESOLVED_UPHELD"):
        raise_err(ERR_INVALID_STATE, "Only a resolved complaint may be escalated")
    complaint["_escalated_from"] = complaint["status"]
    complaint["status"] = "ESCALATED"
    db.touch(complaint)
    # On entry to ESCALATED the complaint leaves the upheld set; posture
    # recomputes (§3.6).
    box = db.boxes.get(complaint["box_id"])
    if box is not None and complaint["_escalated_from"] == "RESOLVED_UPHELD":
        domain.recompute_posture(box)
    return success_object(serialize_complaint(complaint))


@bp.route("/library-network/complaints/<complaint_id>/adjudicate", methods=["POST"])
@require_roles("NetworkAdmin")
def adjudicate_complaint(complaint_id: str, _user_id, _role):
    complaint = _load_complaint(complaint_id)
    body = get_json_body()

    # State precondition (stage 5).
    if complaint["status"] != "ESCALATED":
        raise_err(ERR_INVALID_STATE, "Complaint is not in ESCALATED status")

    # Segregation of duties (stage 7): adjudicator must differ from both the
    # triager and the resolver.
    if _user_id == complaint.get("triaged_by_user_id") or _user_id == complaint.get(
        "resolved_by_user_id"
    ):
        raise_err(ERR_SEGREGATION_OF_DUTIES, "Adjudicator must differ from triager and resolver")

    # Schema (stage 11).
    outcome = require_enum(body, "outcome", RESOLVE_OUTCOMES)
    resolution_notes = optional_string(body, "resolution_notes")

    escalated_from = complaint.get("_escalated_from")
    complaint["outcome"] = outcome
    if resolution_notes is not None:
        complaint["resolution_notes"] = resolution_notes

    if outcome == "UPHELD":
        complaint["status"] = "ADJUDICATED_UPHELD"
        complaint["upheld_at"] = db.now_logical_iso()
        db.touch(complaint)
        if escalated_from == "RESOLVED_DISMISSED":
            # The full upheld cascade fires (first time for this complaint).
            domain.complaint_upheld_cascade(complaint)
        else:
            # Escalated from RESOLVED_UPHELD: the cascade already fired and
            # must not fire twice — but the complaint re-enters the upheld set,
            # so posture recomputes.
            box = db.boxes.get(complaint["box_id"])
            if box is not None:
                domain.recompute_posture(box)
    else:
        complaint["status"] = "ADJUDICATED_DISMISSED"
        db.touch(complaint)
        if escalated_from == "RESOLVED_UPHELD":
            domain.complaint_dismissal_compensation(complaint)
    return success_object(serialize_complaint(complaint))
