"""Identity document endpoints (present, list, get)."""

from flask import Blueprint, request

from errors import err
from db import db, stamp_create
from middleware import require_roles, require_read_role, parse_pagination
from response import object_response
from listing import sorted_collection, paginate_and_respond
from validation import (get_json_body, require_str, require_enum, optional_bool,
                        optional_datetime)
from clock import format_iso8601
import serializers

bp = Blueprint("identity_documents", __name__)

LIST_CATEGORY = {"LIST_A", "LIST_B", "LIST_C"}


@bp.route("/identity-documents", methods=["POST"])
def create_document():
    require_roles({"HRReviewer"})
    body = get_json_body()

    onboarding_id = require_str(body, "onboarding_id")
    # priority 4: existence of the referenced onboarding.
    if onboarding_id not in db.onboardings:
        raise err("ERR_NOT_FOUND", "Onboarding not found")

    list_category = require_enum(body, "list_category", LIST_CATEGORY)
    document_title = require_str(body, "document_title")
    document_number = require_str(body, "document_number")
    expiration = optional_datetime(body, "expiration_date", None)
    is_receipt = optional_bool(body, "is_receipt", False)

    doc = {
        "onboarding_id": onboarding_id,
        "list_category": list_category,
        "document_title": document_title,
        "document_number": document_number,
        "expiration_date": format_iso8601(expiration) if expiration else None,
        "is_receipt": is_receipt,
        "receipt_resolution_deadline": None,
        "accepted_for_section2": False,
        "status": "PRESENTED",
    }
    stamp_create(doc)
    db.identity_documents[doc["id"]] = doc
    return object_response(serializers.identity_document(doc), status=201)


@bp.route("/identity-documents", methods=["GET"])
def list_documents():
    require_read_role()
    limit, offset = parse_pagination()
    records = sorted_collection(db.identity_documents)
    onboarding_id = request.args.get("onboarding_id")
    status = request.args.get("status")
    if onboarding_id is not None:
        records = [r for r in records if r.get("onboarding_id") == onboarding_id]
    if status is not None:
        records = [r for r in records if r.get("status") == status]
    return paginate_and_respond(records, limit, offset,
                                serializers.identity_document)


@bp.route("/identity-documents/<doc_id>", methods=["GET"])
def get_document(doc_id):
    require_read_role()
    doc = db.identity_documents.get(doc_id)
    if doc is None:
        raise err("ERR_NOT_FOUND", "IdentityDocument not found")
    return object_response(serializers.identity_document(doc))
