"""Response envelope helpers (PRD 2.2 / SCAFFOLD response_envelope)."""

from flask import jsonify

from db import db
from util import new_request_id

PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0


def _meta():
    return {
        "api_request_id": new_request_id(),
        "api_request_timestamp": db.now_str(),
    }


def object_response(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def array_response(items, limit, offset, total_count, status=200):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), status


def plain_array_response(items, status=200):
    """Array payload that is not a paginated collection (bulk / substitution)."""
    body = {"meta": _meta(), "response_type": "array", "data": items}
    return jsonify(body), status


def error_response(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status
