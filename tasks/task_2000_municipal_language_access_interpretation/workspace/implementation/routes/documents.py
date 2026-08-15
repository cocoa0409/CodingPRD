"""VitalDocument endpoints (PRD §3.4)."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error,
    ERR_DEPARTMENT_NOT_FOUND,
    ERR_DOCUMENT_NOT_FOUND,
    ERR_INVALID_TRANSITION,
)
from middleware import authorized
from response import success_object
from routes.helpers import get_one, list_endpoint
from services.core import JOB_COMMITTED_STATES, touch
from services.serializers import serialize_document
from util import CLOCK, new_id, next_seq
from validate import get_body, opt_str, reject_unknown_fields, req_enum, req_str, require_path

bp = Blueprint("vital_documents", __name__)

DOC_TYPES = {"FORM", "NOTICE", "GUIDE", "POLICY"}


@bp.post("/vital-documents")
def create_document():
    authorized(["LanguageAccessCoordinator"])
    body = get_body()
    reject_unknown_fields(body, {"department_id", "title", "document_type", "base_language"})
    department_id = req_str(body, "department_id")
    title = req_str(body, "title")
    document_type = req_enum(body, "document_type", DOC_TYPES)
    base_language = opt_str(body, "base_language", default="en")

    require_path("departments", department_id, ERR_DEPARTMENT_NOT_FOUND)

    now = CLOCK.now_iso()
    rec = {
        "id": new_id(),
        "department_id": department_id,
        "title": title,
        "document_type": document_type,
        "base_language": base_language,
        "status": "ACTIVE",
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": next_seq(),
    }
    db["vital_documents"][rec["id"]] = rec
    return success_object(serialize_document(rec), status=201)


@bp.get("/vital-documents")
def list_documents():
    filters = {
        "department_id": request.args.get("department_id"),
        "status": request.args.get("status"),
    }
    return list_endpoint("vital_documents", serialize_document, filters)


@bp.get("/vital-documents/<rid>")
def get_document(rid):
    return get_one("vital_documents", rid, ERR_DOCUMENT_NOT_FOUND, serialize_document)


@bp.post("/vital-documents/<rid>/retire")
def retire_document(rid):
    authorized(["LanguageAccessCoordinator"])
    body = get_body()
    reject_unknown_fields(body, set())
    rec = require_path("vital_documents", rid, ERR_DOCUMENT_NOT_FOUND)
    if rec["status"] != "ACTIVE":
        raise_error(ERR_INVALID_TRANSITION, "only an ACTIVE document may be retired")

    rec["status"] = "RETIRED"
    touch(rec)
    # Cascade: cancel every non-terminal job of this document; each cascaded
    # cancellation releases its provisional commitment derivationally.
    touched_contracts = set()
    for job in db["translation_jobs"].values():
        if job["document_id"] == rid and job["status"] in JOB_COMMITTED_STATES:
            job["status"] = "CANCELLED"
            touch(job)
            if job["vendor_contract_id"] not in touched_contracts:
                touched_contracts.add(job["vendor_contract_id"])
    for cid in touched_contracts:
        contract = db["vendor_contracts"].get(cid)
        if contract is not None:
            touch(contract)
    return success_object(serialize_document(rec))
