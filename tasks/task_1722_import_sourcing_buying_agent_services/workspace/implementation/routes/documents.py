"""Compliance documents: upload, list, get, verify, reject."""

from flask import Blueprint, request

from db import new_id, parse_dt, public, stamp_new, store, touch
from errors import ApiError
from middleware import (
    ALL_ROLES,
    body_json,
    get_or_404,
    paginate,
    req_enum,
    req_str,
    require_roles,
    sorted_created,
)
from response import success_list, success_object
from services.domain import apply_posture, compute_posture

bp = Blueprint("documents", __name__)

DOC_TYPES = ("SOCIAL_AUDIT", "PRODUCT_TEST", "LAB_TEST", "FIRE_SAFETY")


@bp.route("/sourcing/factories/<factoryId>/compliance-documents", methods=["POST"])
def create_document(factoryId):
    require_roles("SourcingAgent")
    factory = get_or_404(store.factories, factoryId, "ERR_FACTORY_NOT_FOUND", "Factory")
    data = body_json()
    doc_type = req_enum(data, "doc_type", DOC_TYPES)
    issued_date = req_str(data, "issued_date")
    expires_at_raw = req_str(data, "expires_at")
    expires_dt = parse_dt(expires_at_raw)
    if expires_dt is None:
        raise ApiError("ERR_VALIDATION", "expires_at must be an ISO 8601 datetime", 400)
    doc = stamp_new(
        {
            "id": new_id(),
            "factory_id": factory["id"],
            "doc_type": doc_type,
            "issued_date": issued_date,
            "expires_at": expires_at_raw,
            "status": "SUBMITTED",
            "_expires_dt": expires_dt,
        }
    )
    store.documents[doc["id"]] = doc
    return success_object(public(doc), 201)


@bp.route("/sourcing/compliance-documents", methods=["GET"])
def list_documents():
    require_roles(*ALL_ROLES)
    items = list(store.documents.values())
    factory_id = request.args.get("factory_id")
    doc_type = request.args.get("doc_type")
    status = request.args.get("status")
    if factory_id is not None:
        items = [d for d in items if d["factory_id"] == factory_id]
    if doc_type is not None:
        items = [d for d in items if d["doc_type"] == doc_type]
    if status is not None:
        items = [d for d in items if d["status"] == status]
    items = sorted_created(items)
    page, limit, offset, total = paginate(items)
    return success_list([public(d) for d in page], limit, offset, total)


@bp.route("/sourcing/compliance-documents/<docId>", methods=["GET"])
def get_document(docId):
    require_roles(*ALL_ROLES)
    doc = get_or_404(
        store.documents, docId, "ERR_COMPLIANCE_DOCUMENT_NOT_FOUND", "ComplianceDocument"
    )
    return success_object(public(doc))


@bp.route("/sourcing/compliance-documents/<docId>/verify", methods=["POST"])
def verify_document(docId):
    require_roles("ComplianceOfficer")
    doc = get_or_404(
        store.documents, docId, "ERR_COMPLIANCE_DOCUMENT_NOT_FOUND", "ComplianceDocument"
    )
    if doc["status"] != "SUBMITTED":
        raise ApiError(
            "ERR_DOC_NOT_VERIFIABLE", "ComplianceDocument is not SUBMITTED", 409
        )
    doc["status"] = "VERIFIED"
    touch(doc)
    factory = store.factories.get(doc["factory_id"])
    if factory is not None:
        apply_posture(factory, compute_posture(factory["id"]))
    return success_object(public(doc))


@bp.route("/sourcing/compliance-documents/<docId>/reject", methods=["POST"])
def reject_document(docId):
    require_roles("ComplianceOfficer")
    doc = get_or_404(
        store.documents, docId, "ERR_COMPLIANCE_DOCUMENT_NOT_FOUND", "ComplianceDocument"
    )
    if doc["status"] != "SUBMITTED":
        raise ApiError(
            "ERR_DOC_NOT_VERIFIABLE", "ComplianceDocument is not SUBMITTED", 409
        )
    doc["status"] = "REJECTED"
    touch(doc)
    return success_object(public(doc))
