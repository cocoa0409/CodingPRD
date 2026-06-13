"""Supporting documents: attach, read, list, and verify (accept/reject)."""
from __future__ import annotations

from flask import Blueprint

import db
from errors import (
    APIError,
    ERR_ALREADY_TERMINAL,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_NOT_FOUND,
    ERR_SOD_VIOLATION,
    ERR_VALIDATION,
)
from middleware import current_user_id, require_auth
from response import ok_array, ok_object
from routes._helpers import (
    get_body,
    order_by_created,
    paginate,
    parse_pagination,
    require_enum,
    require_str,
    serialize,
    serialize_list,
    stamp_create,
    touch,
)
from services import domain

bp = Blueprint("documents", __name__)

DOC_CATEGORIES = {"IDENTITY", "CITIZENSHIP", "GUARDIAN_CONSENT", "NAME_CHANGE_EVIDENCE"}


def _app_or_404(rid: str) -> dict:
    rec = db.applications.get(rid)
    if rec is None:
        raise APIError(ERR_NOT_FOUND, 404, "Application not found")
    return rec


def _doc_or_404(rid: str) -> dict:
    rec = db.supporting_documents.get(rid)
    if rec is None:
        raise APIError(ERR_NOT_FOUND, 404, "SupportingDocument not found")
    return rec


@bp.route("/applications/<rid>/documents", methods=["POST"])
def attach_document(rid):
    require_auth(["Applicant"])
    app_rec = _app_or_404(rid)
    body = get_body()
    for f in ("doc_category", "doc_kind"):
        if f not in body or body.get(f) is None:
            raise APIError(ERR_INVALID_REQUEST, 400, f"Missing required field: {f}")
    doc_category = require_enum(body, "doc_category", DOC_CATEGORIES)
    doc_kind = require_str(body, "doc_kind")

    declared_quality = 100
    if "declared_quality" in body and body["declared_quality"] is not None:
        dq = body["declared_quality"]
        if isinstance(dq, bool) or not isinstance(dq, int):
            raise APIError(ERR_INVALID_REQUEST, 400, "declared_quality must be an integer")
        if dq < 0 or dq > 100:
            raise APIError(ERR_VALIDATION, 422, "declared_quality must be in 0..100")
        declared_quality = dq

    doc = {
        "application_id": rid,
        "doc_category": doc_category,
        "doc_kind": doc_kind,
        "declared_quality": declared_quality,
        "verification_status": "PENDING",
        "reviewed_by_agent_id": None,
    }
    stamp_create(doc, full=True)
    db.supporting_documents[doc["id"]] = doc
    return ok_object(serialize(doc), 201)


@bp.route("/applications/<rid>/documents", methods=["GET"])
def list_documents(rid):
    require_auth(["Applicant", "AcceptanceAgent", "Adjudicator"])
    _app_or_404(rid)
    limit, offset = parse_pagination()
    items = [d for d in db.supporting_documents.values() if d["application_id"] == rid]
    items = order_by_created(items)
    page, total = paginate(items, limit, offset)
    return ok_array(serialize_list(page), limit, offset, total, 200)


@bp.route("/documents/<rid>", methods=["GET"])
def get_document(rid):
    require_auth(["Applicant", "AcceptanceAgent", "Adjudicator"])
    rec = _doc_or_404(rid)
    return ok_object(serialize(rec), 200)


@bp.route("/documents/<rid>/verify", methods=["POST"])
def verify_document(rid):
    require_auth(["AcceptanceAgent"])
    doc = _doc_or_404(rid)
    body = get_body()

    app_rec = db.applications[doc["application_id"]]

    # 5 / 6 transition definedness & terminality (document level)
    if doc["verification_status"] in ("ACCEPTED", "REJECTED"):
        raise APIError(ERR_ALREADY_TERMINAL, 409, "Document is already verified")
    # parent application must be IN_VERIFICATION
    if app_rec["status"] != "IN_VERIFICATION":
        raise APIError(ERR_INVALID_STATE, 409, "Parent application must be IN_VERIFICATION")

    # 7 SoD — acting agent must be the assigned agent
    agent_id = current_user_id()
    if agent_id != app_rec.get("assigned_acceptance_agent_id"):
        raise APIError(ERR_SOD_VIOLATION, 403, "Only the assigned acceptance agent may verify")

    # 18 request well-formedness (priority last per PRD §2.9)
    if "outcome" not in body or body.get("outcome") is None:
        raise APIError(ERR_INVALID_REQUEST, 400, "Missing required field: outcome")
    outcome = require_enum(body, "outcome", {"ACCEPT", "REJECT"})

    doc["reviewed_by_agent_id"] = agent_id

    if outcome == "ACCEPT":
        doc["verification_status"] = "ACCEPTED"
        touch(doc)
        touch(app_rec)  # parent version bump for the document mutation

        # CASCADE: name-change evidence advances the sub-status
        if doc["doc_category"] == "NAME_CHANGE_EVIDENCE" and app_rec["name_change_status"] == "PENDING_EVIDENCE":
            app_rec["name_change_status"] = "EVIDENCE_VERIFIED"
            touch(app_rec)

        # FINAL risk recompute (mutates applicant)
        applicant = db.applicants[app_rec["applicant_id"]]
        score = domain.recompute_risk_final(applicant)

        # CASCADE: last-required-accept auto-advance, else independent risk gate
        if domain.all_required_accepted(app_rec) and app_rec["name_change_status"] in ("NONE", "APPROVED"):
            domain.maybe_auto_advance_verification(app_rec, "system")
        else:
            domain.maybe_review_hold_on_risk(app_rec, score)
    else:  # REJECT
        doc["verification_status"] = "REJECTED"
        touch(doc)
        touch(app_rec)
        applicant = db.applicants[app_rec["applicant_id"]]
        score = domain.recompute_risk_final(applicant)
        domain.maybe_review_hold_on_risk(app_rec, score)

    return ok_object(serialize(doc), 200)
