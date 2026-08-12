"""Required documents and source-plan verifications (PRD §3.4, §3.5)."""

from flask import Blueprint, g

import errors
from db import now_iso, store, touch
from middleware import body, req_enum, require_roles
from response import ok
from services import case_owner_participant_id, docs_of_case, serialize_document, serialize_verification

bp = Blueprint("docs", __name__)


def _get_doc_or_404(doc_id, ownership_mask=True):
    d = store.documents.get(doc_id)
    if d is None:
        raise errors.err_document_not_found()
    if ownership_mask and g.role == "Participant":
        case = store.cases.get(d["rollover_case_id"])
        if case is None or case_owner_participant_id(case) != g.user_id:
            raise errors.err_case_not_found()
    return d


def _bubble_up(case):
    """DOCS_PENDING -> ELIGIBILITY_REVIEW once every row is SUBMITTED or ACCEPTED
    (no REQUIRED and no REJECTED rows remain) — PRD §3.4 / SCAFFOLD §1.2."""
    if case["status"] != "DOCS_PENDING":
        return
    docs = docs_of_case(case["id"])
    if docs and all(d["status"] in ("SUBMITTED", "ACCEPTED") for d in docs):
        case["status"] = "ELIGIBILITY_REVIEW"
        touch(case)


@bp.post("/v1/documents/<doc_id>/submit")
@require_roles("Participant")
def submit_document(doc_id):
    doc = _get_doc_or_404(doc_id)
    if doc["status"] not in ("REQUIRED", "REJECTED"):
        raise errors.err_document_invalid_state("Document is not in a submittable state")
    case = store.cases.get(doc["rollover_case_id"])
    if case is None or case["status"] != "DOCS_PENDING":
        raise errors.err_case_invalid_state("Owning case is not DOCS_PENDING")
    doc["status"] = "SUBMITTED"
    doc["submitted_by"] = g.user_id
    doc["reviewed_by"] = None  # resubmission clears the prior reviewer
    touch(doc)
    _bubble_up(case)
    return ok(serialize_document(doc))


@bp.post("/v1/documents/<doc_id>/review")
@require_roles("RolloverProcessor")
def review_document(doc_id):
    doc = _get_doc_or_404(doc_id, ownership_mask=False)
    data = body()
    decision = req_enum(data, "decision", {"ACCEPTED", "REJECTED"})
    if doc["status"] != "SUBMITTED":
        raise errors.err_document_invalid_state("Document is not SUBMITTED")
    case = store.cases.get(doc["rollover_case_id"])
    doc["reviewed_by"] = g.user_id
    if decision == "ACCEPTED":
        doc["status"] = "ACCEPTED"
        touch(doc)
        if case is not None:
            _bubble_up(case)
    else:
        note = data.get("review_note")
        if not isinstance(note, str) or not note:
            raise errors.err_validation("review_note is required when decision is REJECTED")
        doc["status"] = "REJECTED"
        doc["review_note"] = note
        touch(doc)
        # Rejection reopens the docs loop (PRD §3.4).
        if case is not None and case["status"] == "ELIGIBILITY_REVIEW":
            case["status"] = "DOCS_PENDING"
            touch(case)
    return ok(serialize_document(doc))


@bp.post("/v1/verifications/<ver_id>/complete")
@require_roles("RolloverProcessor")
def complete_verification(ver_id):
    ver = store.verifications.get(ver_id)
    if ver is None:
        raise errors.err_verification_not_found()
    data = body()
    outcome = req_enum(data, "outcome", {"VERIFIED", "FAILED"})
    if ver["status"] != "PENDING":
        raise errors.err_verification_invalid_state("Verification is already completed")
    ver["status"] = outcome
    if outcome == "VERIFIED":
        ver["verified_at"] = now_iso()
    touch(ver)
    return ok(serialize_verification(ver))
