"""DocumentIntake, FeeLine, and EfileSubmission listing endpoints (PRD §3.3,
§3.4, §3.5)."""
from flask import Blueprint

import errors
from db import db
from middleware import get_identity, require_role
from models import (make_document, document_dict, fee_line_dict,
                    efile_submission_dict, touch)
from response import object_response, array_response
from routes.common import (get_json_body, get_return, get_document, paginate, page_slice)
from constants import DOC_TYPES

bp = Blueprint("documents", __name__)


@bp.post("/returns/<return_id>/documents")
def add_document(return_id):
    _, role = get_identity()
    require_role(role, {"FrontDeskAgent", "OfficeManager", "TaxPreparer"})
    get_return(return_id)
    body = get_json_body()

    doc_type = body.get("doc_type")
    if doc_type not in DOC_TYPES:
        raise errors.err(errors.ERR_INVALID_REQUEST, "doc_type is invalid")

    is_required = body.get("is_required", True)
    if not isinstance(is_required, bool):
        raise errors.err(errors.ERR_INVALID_REQUEST, "is_required must be boolean")

    doc = make_document(return_id, doc_type, is_required)
    return object_response(document_dict(doc), 201)


@bp.get("/returns/<return_id>/documents")
def list_documents(return_id):
    _, role = get_identity()
    require_role(role, {"FrontDeskAgent", "OfficeManager", "TaxPreparer"})
    get_return(return_id)
    limit, offset = paginate()

    items = [d for d in db.documents.values() if d["tax_return_id"] == return_id]
    page, total = page_slice(items, limit, offset)
    return array_response([document_dict(d) for d in page], limit, offset, total, 200)


@bp.post("/documents/<document_id>/status")
def set_document_status(document_id):
    _, role = get_identity()
    require_role(role, {"FrontDeskAgent", "OfficeManager", "TaxPreparer"})
    doc = get_document(document_id)
    body = get_json_body()

    status = body.get("status")
    if status not in ("RECEIVED", "WAIVED"):
        raise errors.err(errors.ERR_INVALID_REQUEST, "status must be RECEIVED or WAIVED")

    doc["status"] = status
    touch(doc)
    return object_response(document_dict(doc), 200)


@bp.get("/returns/<return_id>/fee-lines")
def list_fee_lines(return_id):
    _, role = get_identity()
    require_role(role, {"FrontDeskAgent", "OfficeManager", "TaxPreparer", "BankProductOfficer"})
    get_return(return_id)
    limit, offset = paginate()

    items = [f for f in db.fee_lines.values() if f["tax_return_id"] == return_id]
    page, total = page_slice(items, limit, offset)
    return array_response([fee_line_dict(f) for f in page], limit, offset, total, 200)


@bp.get("/returns/<return_id>/efile-submissions")
def list_efile_submissions(return_id):
    _, role = get_identity()
    require_role(role, {"TaxPreparer", "OfficeManager"})
    get_return(return_id)
    limit, offset = paginate()

    items = [s for s in db.efile_submissions.values() if s["tax_return_id"] == return_id]
    page, total = page_slice(items, limit, offset)
    return array_response([efile_submission_dict(s) for s in page], limit, offset, total, 200)
