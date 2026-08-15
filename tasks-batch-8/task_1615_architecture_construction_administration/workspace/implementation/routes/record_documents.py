"""RecordDocument endpoints."""

from flask import Blueprint, request

import db
from errors import (
    ApiError,
    ERR_RECORD_DOCUMENT_INVALID_STATE,
    ERR_DUPLICATE_RECORD_DOCUMENT,
)
from middleware import get_user_context, require_role, get_body
from response import success_object, success_list
from services.helpers import (
    base_entity, touch, paginate, get_project, get_record_document,
    req_str, opt_str, opt_enum,
)
from services.lifecycle import require_project_active, check_counterparty

bp = Blueprint("record_documents", __name__)

ALL_ROLES = ("FirmAdmin", "ArchitectCA", "Contractor", "Owner")
DOC_TYPES = ("AS_BUILT", "OM_MANUAL", "WARRANTY", "TEST_REPORT")
REVIEW_OUTCOMES = ("ACCEPT", "RETURN_FOR_CORRECTION")


@bp.post("/ca/record-documents")
def create_record_document():
    user_id, role = get_user_context()
    require_role(role, ("Contractor",))
    body = get_body(required=True)
    project_id = req_str(body, "project_id")
    doc_type = opt_enum(body, "doc_type", DOC_TYPES)

    project = get_project(project_id)
    check_counterparty(role, user_id, project)
    # Record documents may be created while ACTIVE or SUBSTANTIAL_COMPLETION_ACHIEVED.
    require_project_active(project, allow_substantial=True)

    # One live record document per (project, doc_type).
    duplicate = any(
        d["project_id"] == project_id
        and d["doc_type"] == doc_type
        and d["status"] in ("SUBMITTED", "RETURNED_FOR_CORRECTION", "ACCEPTED")
        for d in db.record_documents.values()
    )
    if duplicate:
        raise ApiError(
            ERR_DUPLICATE_RECORD_DOCUMENT,
            "A non-terminal record document of the same doc_type already exists on the project",
            409,
        )

    doc = base_entity()
    doc.update({
        "project_id": project_id,
        "doc_type": doc_type,
        "revision_number": 1,
        "review_notes": None,
        "status": "SUBMITTED",
    })
    db.record_documents[doc["id"]] = doc
    return success_object(doc, 201)


@bp.get("/ca/record-documents")
def list_record_documents():
    _, role = get_user_context()
    require_role(role, ALL_ROLES)
    items = list(db.record_documents.values())
    project_id = request.args.get("project_id")
    if project_id is not None:
        items = [d for d in items if d["project_id"] == project_id]
    status = request.args.get("status")
    if status is not None:
        items = [d for d in items if d["status"] == status]
    doc_type = request.args.get("doc_type")
    if doc_type is not None:
        items = [d for d in items if d["doc_type"] == doc_type]
    page, limit, offset, total = paginate(items)
    return success_list(page, limit, offset, total)


@bp.get("/ca/record-documents/<did>")
def get_one_record_document(did):
    _, role = get_user_context()
    require_role(role, ALL_ROLES)
    return success_object(get_record_document(did))


@bp.post("/ca/record-documents/<did>/review")
def review_record_document(did):
    _, role = get_user_context()
    require_role(role, ("ArchitectCA",))
    body = get_body(required=True)
    outcome = opt_enum(body, "outcome", REVIEW_OUTCOMES)
    review_notes = opt_str(body, "review_notes", None)
    doc = get_record_document(did)
    if doc["status"] != "SUBMITTED":
        raise ApiError(
            ERR_RECORD_DOCUMENT_INVALID_STATE,
            "record-document review requires SUBMITTED",
            409,
        )
    doc["review_notes"] = review_notes
    doc["status"] = "ACCEPTED" if outcome == "ACCEPT" else "RETURNED_FOR_CORRECTION"
    touch(doc)
    return success_object(doc)


@bp.post("/ca/record-documents/<did>/resubmit")
def resubmit_record_document(did):
    user_id, role = get_user_context()
    require_role(role, ("Contractor",))
    doc = get_record_document(did)
    project = db.projects[doc["project_id"]]
    check_counterparty(role, user_id, project)
    if doc["status"] != "RETURNED_FOR_CORRECTION":
        raise ApiError(
            ERR_RECORD_DOCUMENT_INVALID_STATE,
            "record-document resubmit requires RETURNED_FOR_CORRECTION",
            409,
        )
    doc["revision_number"] += 1
    doc["status"] = "SUBMITTED"
    touch(doc)
    return success_object(doc)
