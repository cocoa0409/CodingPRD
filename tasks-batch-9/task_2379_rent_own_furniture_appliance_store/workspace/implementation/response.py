"""Standard response envelope (PRD 2.2) and pagination (PRD 2.3)."""

import random
import string

from flask import jsonify

import clock

ALPHANUM = string.ascii_uppercase + string.digits

PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0


def _request_id():
    return "req_" + "".join(random.choice(ALPHANUM) for _ in range(20))


def _meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": clock.now_str(),
    }


def object_response(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data or {}}
    return jsonify(body), status


def list_response(items, limit, offset, total_count, status=200):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), status


def error_response(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status
