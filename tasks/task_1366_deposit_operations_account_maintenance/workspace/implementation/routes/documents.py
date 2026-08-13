"""AccountDocument endpoints (PRD §3.2)."""

from flask import Blueprint, request

import db
from errors import (
    ApiError,
    ERR_DUPLICATE_REFERENCE,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_NOT_FOUND,
)
from middleware import require_roles
from response import paginate, parse_pagination, success_list, success_object
from serialization import document_view
from services.account import get_account_or_404, touch_resource

bp = Blueprint("documents", __name__)

DOC_TYPES = {
    "SIGNATURE_CARD",
    "DEATH_CERTIFICATE",
    "LETTERS_TESTAMENTARY",
    "TRUST_AGREEMENT",
    "POD_DESIGNATION",
    "BUSINESS_RESOLUTION",
    "COURT_ORDER",
}


@bp.post("/bank/accounts/<account_id>/documents")
def submit_document(account_id):
    require_roles(["OpsOfficer"])
    get_account_or_404(account_id)
    body = request.get_json(silent=True) or {}

    doc_type = body.get("doc_type")
    if doc_type not in DOC_TYPES:
        raise ApiError(ERR_INVALID_REQUEST, "doc_type must be a declared member")
    reference_number = body.get("reference_number")
    if not isinstance(reference_number, str) or not reference_number.strip():
        raise ApiError(ERR_INVALID_REQUEST, "reference_number is required")

    # reference_number is unique per account across all statuses (PRD §3.2).
    duplicate = any(
        d["account_id"] == account_id and d["reference_number"] == reference_number
        for d in db.documents.values()
    )
    if duplicate:
        raise ApiError(
            ERR_DUPLICATE_REFERENCE,
            "reference_number is already used on this account",
        )

    doc = {
        "id": db.new_uuid(),
        "account_id": account_id,
        "doc_type": doc_type,
        "reference_number": reference_number,
        "status": "SUBMITTED",
        "reviewed_by_user_id": None,
        "review_note": None,
        "created_at": db.now_timestamp(),
        "updated_at": db.now_timestamp(),
        "version": 1,
        "_seq": db.next_creation_seq(),
    }
    db.documents[doc["id"]] = doc
    return success_object(document_view(doc), status=201)


@bp.post("/bank/documents/<document_id>/review")
def review_document(document_id):
    user_id, _ = require_roles(["OpsManager"])
    doc = db.documents.get(document_id)
    if doc is None:
        raise ApiError(ERR_NOT_FOUND, f"Document {document_id} does not exist")
    body = request.get_json(silent=True) or {}

    decision = body.get("decision")
    if decision not in ("VERIFIED", "REJECTED"):
        raise ApiError(ERR_INVALID_REQUEST, "decision must be VERIFIED or REJECTED")
    review_note = body.get("review_note")
    if review_note is not None and not isinstance(review_note, str):
        raise ApiError(ERR_INVALID_REQUEST, "review_note must be a string")

    if doc["status"] != "SUBMITTED":
        raise ApiError(ERR_INVALID_STATE, "Only a SUBMITTED document can be reviewed")

    doc["status"] = decision
    doc["reviewed_by_user_id"] = user_id
    doc["review_note"] = review_note
    touch_resource(doc)
    return success_object(document_view(doc))


@bp.get("/bank/accounts/<account_id>/documents")
def list_documents(account_id):
    require_roles(["OpsOfficer", "OpsManager", "Auditor", "System"])
    get_account_or_404(account_id)
    limit, offset = parse_pagination(request.args)
    doc_type = request.args.get("doc_type")
    status = request.args.get("status")

    items = [d for d in db.documents.values() if d["account_id"] == account_id]
    items.sort(key=lambda d: d["_seq"])
    if doc_type is not None:
        items = [d for d in items if d["doc_type"] == doc_type]
    if status is not None:
        items = [d for d in items if d["status"] == status]
    total = len(items)
    page = paginate(items, limit, offset)
    return success_list([document_view(d) for d in page], total, limit, offset)
