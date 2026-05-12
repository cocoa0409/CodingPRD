"""Query response/resolve endpoints."""

from flask import Blueprint, g

from db import DB, LOCK
from errors import (
    APIError,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE_TRANSITION,
    ERR_QUERY_DOCUMENTS_INCOMPLETE,
    forbidden,
    not_found,
)
from middleware import require_roles
from response import success_object
from services.common import check_occ, emit_audit, get_body, touch
from services.serializers import serialize_query


bp = Blueprint("queries", __name__)


@bp.route("/queries/<query_id>/respond", methods=["POST"])
@require_roles("Declarant")
def respond_query(query_id):
    body = get_body()
    response_text = body.get("response_text")
    response_documents = body.get("response_documents")
    if not isinstance(response_documents, list):
        raise APIError(ERR_INVALID_REQUEST, "response_documents must be array", 400)

    with LOCK:
        q = DB.queries.get(query_id)
        if q is None:
            raise not_found("Query not found")
        dec = DB.declarations.get(q["declaration_id"])
        if dec is None:
            raise not_found("Declaration not found")
        if dec["declarant_id"] != g.user_id:
            raise forbidden("Declarant does not own this query")
        if q["status"] != "OPEN":
            raise APIError(ERR_INVALID_STATE_TRANSITION,
                           "Respond only allowed when query is OPEN", 409)

        # Document completeness — every required doc_type must appear in response_documents
        required = q.get("required_documents") or []
        provided_types = []
        for d in response_documents:
            if isinstance(d, dict) and "doc_type" in d:
                provided_types.append(d["doc_type"])
        for req in required:
            if req not in provided_types:
                raise APIError(ERR_QUERY_DOCUMENTS_INCOMPLETE,
                               f"Missing required document type: {req}", 422)

        check_occ(q, body)
        q["response_text"] = response_text
        q["response_documents"] = list(response_documents)
        q["status"] = "RESPONDED"
        touch(q)
        return success_object(serialize_query(q), status=200)


@bp.route("/queries/<query_id>/resolve", methods=["POST"])
@require_roles("CustomsOfficer")
def resolve_query(query_id):
    body = get_body()
    with LOCK:
        q = DB.queries.get(query_id)
        if q is None:
            raise not_found("Query not found")
        if q["status"] != "RESPONDED":
            raise APIError(ERR_INVALID_STATE_TRANSITION,
                           "Resolve only allowed when query is RESPONDED", 409)
        check_occ(q, body)
        q["status"] = "RESOLVED"
        touch(q)
        # Cascade declaration QUERIED → UNDER_REVIEW
        dec = DB.declarations.get(q["declaration_id"])
        if dec is not None and dec["status"] == "QUERIED":
            before = {"status": "QUERIED", "query_id": dec.get("query_id")}
            dec["query_id"] = None
            dec["status"] = "UNDER_REVIEW"
            touch(dec)
            emit_audit("DECLARATION", dec["id"], "DECLARATION_STATUS_CHANGE",
                       before_value=before,
                       after_value={"status": "UNDER_REVIEW", "query_id": None})
        return success_object(serialize_query(q), status=200)
