"""ComplianceDocument routes."""

from flask import Blueprint, request

import errors
import middleware
from db import db
from response import success
from services.core import base_entity, touch, recompute_classification, evaluate_doc_expiry
from services.serialize import serialize_doc
from util import get_body, req_str, req_enum, req_dt, opt_str, parse_pagination, paginate

bp = Blueprint("compliance", __name__)

DOC_TYPES = {"W9", "OPERATING_AUTHORITY", "INSURANCE_CERTIFICATE", "MEDICAL_CARD"}


def _get_doc_or_404(doc_id):
    d = db.compliance_documents.get(doc_id)
    if d is None:
        raise errors.err(errors.ERR_DOC_NOT_FOUND, "ComplianceDocument not found", 404)
    return d


@bp.post("/compliance-documents")
def create_doc():
    middleware.require_roles({"ComplianceOfficer"})
    body = get_body()
    owner_operator_id = req_str(body, "owner_operator_id")
    doc_type = req_enum(body, "doc_type", DOC_TYPES)
    expires_on = req_dt(body, "expires_on")

    if owner_operator_id not in db.owner_operators:
        raise errors.err(errors.ERR_OPERATOR_NOT_FOUND, "OwnerOperator not found", 404)

    doc = base_entity()
    doc.update({
        "owner_operator_id": owner_operator_id,
        "doc_type": doc_type,
        "_expires_on": expires_on,
        "status": "SUBMITTED",
        "rejection_reason": None,
    })
    db.compliance_documents[doc["id"]] = doc
    return success(serialize_doc(doc), "object", 201)


@bp.get("/compliance-documents")
def list_docs():
    middleware.require_roles(middleware.ALL_ROLES)
    limit, offset = parse_pagination()
    items = list(db.compliance_documents.values())
    op_filter = request.args.get("owner_operator_id")
    status_filter = request.args.get("status")
    changed_ops = set()
    for d in items:
        if evaluate_doc_expiry(d):
            changed_ops.add(d["owner_operator_id"])
    for op_id in changed_ops:
        op = db.owner_operators.get(op_id)
        if op is not None:
            recompute_classification(op)
    if op_filter is not None:
        items = [d for d in items if d["owner_operator_id"] == op_filter]
    if status_filter is not None:
        items = [d for d in items if d["status"] == status_filter]
    items.sort(key=lambda d: (d["created_at"], d["id"]))
    page, pg = paginate(items, limit, offset)
    return success([serialize_doc(d) for d in page], "array", 200, pagination=pg)


@bp.get("/compliance-documents/<doc_id>")
def get_doc(doc_id):
    middleware.require_roles(middleware.ALL_ROLES)
    d = _get_doc_or_404(doc_id)
    if evaluate_doc_expiry(d):
        op = db.owner_operators.get(d["owner_operator_id"])
        if op is not None:
            recompute_classification(op)
    return success(serialize_doc(d), "object", 200)


@bp.post("/compliance-documents/<doc_id>/verify")
def verify_doc(doc_id):
    middleware.require_roles({"ComplianceOfficer"})
    d = _get_doc_or_404(doc_id)
    if d["status"] != "SUBMITTED":
        raise errors.err(errors.ERR_DOC_ALREADY_REVIEWED, "Document is not SUBMITTED", 409)
    d["status"] = "VERIFIED"
    touch(d)
    op = db.owner_operators.get(d["owner_operator_id"])
    if op is not None:
        recompute_classification(op)
    return success(serialize_doc(d), "object", 200)


@bp.post("/compliance-documents/<doc_id>/reject")
def reject_doc(doc_id):
    middleware.require_roles({"ComplianceOfficer"})
    d = _get_doc_or_404(doc_id)
    body = get_body()
    reason = opt_str(body, "reason")
    if d["status"] != "SUBMITTED":
        raise errors.err(errors.ERR_DOC_ALREADY_REVIEWED, "Document is not SUBMITTED", 409)
    d["status"] = "REJECTED"
    d["rejection_reason"] = reason
    touch(d)
    op = db.owner_operators.get(d["owner_operator_id"])
    if op is not None:
        recompute_classification(op)
    return success(serialize_doc(d), "object", 200)
