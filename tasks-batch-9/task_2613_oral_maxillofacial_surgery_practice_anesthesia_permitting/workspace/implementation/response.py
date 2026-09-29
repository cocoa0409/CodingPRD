"""Response envelope helpers (SCAFFOLD response_envelope / PRD 2.2, 2.3)."""
import random
import string

from flask import jsonify, request

from errors import ERROR_CATALOG
from timeutil import fmt_dt, now_real

_ALPHANUM = string.ascii_uppercase + string.digits

PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0


def new_request_id():
    return "req_" + "".join(random.choice(_ALPHANUM) for _ in range(20))


def base_meta():
    return {
        "api_request_id": new_request_id(),
        "api_request_timestamp": fmt_dt(now_real()),
    }


def object_response(data, status=200):
    body = {"meta": base_meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def list_response(items, total_count, limit, offset, status=200):
    meta = base_meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), status


def error_response(error_id, message):
    body = {
        "meta": base_meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), ERROR_CATALOG.get(error_id, 400)


def paginate(items):
    """Apply the query-string window to an already ordered collection."""
    from validation import read_pagination

    limit, offset = read_pagination()
    total = len(items)
    window = items[offset:offset + limit]
    return window, total, limit, offset
