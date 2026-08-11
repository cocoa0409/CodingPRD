"""Documents, index records, page logs (document-scoped)."""

from flask import Blueprint, request

from db import db
from errors import (
    ApiError,
    ERR_NOT_FOUND,
    ERR_INVALID_STATE,
    ERR_METADATA_INCOMPLETE,
    ERR_CLIENT_SUSPENDED,
)
from middleware import require_roles, check_client_user_scope
from response import success_object, success_list, parse_pagination
from util import get_body, require_fields, reject_unknown, as_str, make_entity, bump
from services.serializers import (
    document_view,
    index_record_view,
    page_log_view,
)
from services.pricing import MIN_OCR_CONFIDENCE

bp = Blueprint("documents", __name__)

ALL_ROLES = (
    "PlatformAdmin", "IntakeClerk", "PrepTechnician", "ScanOperator", "QAReviewer",
    "Indexer", "DestructionSpecialist", "ComplianceOfficer", "BillingClerk", "ClientUser",
)
STAFF_ROLES = (
    "PlatformAdmin", "IntakeClerk", "PrepTechnician", "ScanOperator", "QAReviewer",
    "Indexer", "DestructionSpecialist", "ComplianceOfficer", "BillingClerk",
)


def get_doc_or_404(doc_id):
    d = db.documents.get(doc_id)
    if not d:
        raise ApiError(ERR_NOT_FOUND, "Document not found", 404)
    return d


def doc_client_id(doc):
    batch = db.batches.get(doc["batch_id"])
    return batch["client_id"] if batch else None


def check_client_active_for_doc(doc):
    batch = db.batches.get(doc["batch_id"])
    if batch:
        client = db.clients.get(batch["client_id"])
        if client and client["status"] == "SUSPENDED":
            raise ApiError(ERR_CLIENT_SUSPENDED, "Client is suspended", 403)


@bp.route("/documents/<id>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_document(id, _user_id, _role):
    doc = get_doc_or_404(id)
    check_client_user_scope(_user_id, _role, doc_client_id(doc))
    return success_object(document_view(doc))


@bp.route("/documents/<id>/index-records", methods=["POST"])
@require_roles("Indexer")
def submit_index_record(id, _user_id, _role):
    doc = get_doc_or_404(id)
    body = get_body()
    require_fields(body, ["metadata_json", "ocr_text_ref"])
    reject_unknown(body, {"metadata_json", "ocr_text_ref"})
    metadata_json = body["metadata_json"]
    if not isinstance(metadata_json, dict):
        raise ApiError(ERR_METADATA_INCOMPLETE, "metadata_json must be an object", 422)
    ocr_text_ref = as_str(body["ocr_text_ref"], "ocr_text_ref")
    check_client_active_for_doc(doc)
    batch = db.batches.get(doc["batch_id"])
    if not batch or batch["status"] != "INDEXING":
        raise ApiError(ERR_INVALID_STATE, "Batch is not in INDEXING", 409)
    if doc["status"] != "SCANNED":
        raise ApiError(ERR_INVALID_STATE, "Document is not SCANNED", 409)
    # Metadata completeness
    for key in ("title", "record_date", "subject"):
        if key not in metadata_json:
            raise ApiError(
                ERR_METADATA_INCOMPLETE, f"metadata_json missing key: {key}", 422
            )
    # OCR confidence fork
    if doc["ocr_confidence"] < MIN_OCR_CONFIDENCE:
        # SCANNED -> REJECTED; respond 200 with the Document, no IndexRecord
        doc["status"] = "REJECTED"
        bump(doc)
        return success_object(document_view(doc), status=200)
    record = make_entity(
        {
            "document_id": doc["id"],
            "batch_id": doc["batch_id"],
            "metadata_json": metadata_json,
            "ocr_text_ref": ocr_text_ref,
        }
    )
    db.index_records[record["id"]] = record
    doc["status"] = "INDEXED"
    bump(doc)
    return success_object(index_record_view(record), status=201)


@bp.route("/documents/<id>/index-records", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_doc_index_records(id, _user_id, _role):
    doc = get_doc_or_404(id)
    check_client_user_scope(_user_id, _role, doc_client_id(doc))
    limit, offset = parse_pagination(request.args)
    items = [r for r in db.index_records.values() if r["document_id"] == id]
    items.sort(key=lambda r: (r["created_at"], r["id"]))
    total = len(items)
    page = items[offset : offset + limit]
    return success_list([index_record_view(r) for r in page], limit, offset, total)


@bp.route("/index-records/<id>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_index_record(id, _user_id, _role):
    r = db.index_records.get(id)
    if not r:
        raise ApiError(ERR_NOT_FOUND, "Index record not found", 404)
    doc = db.documents.get(r["document_id"])
    if doc:
        check_client_user_scope(_user_id, _role, doc_client_id(doc))
    return success_object(index_record_view(r))


@bp.route("/documents/<id>/page-logs", methods=["GET"])
@require_roles(*STAFF_ROLES)
def get_doc_page_logs(id, _user_id, _role):
    get_doc_or_404(id)
    limit, offset = parse_pagination(request.args)
    items = [p for p in db.page_logs.values() if p["document_id"] == id]
    items.sort(key=lambda p: (p["created_at"], p["id"]))
    total = len(items)
    page = items[offset : offset + limit]
    return success_list([page_log_view(p) for p in page], limit, offset, total)
