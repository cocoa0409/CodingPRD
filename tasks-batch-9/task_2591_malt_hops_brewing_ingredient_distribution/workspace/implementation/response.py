"""Response envelope helpers.

Success:  {"meta": {...}, "response_type": "object"|"array", "data": ...}
Error:    {"meta": {...}, "response_type": "error",
           "data": {"error_id": "...", "message": "..."}}
"""

import random
import string
from datetime import datetime, timezone

from flask import jsonify

from util import fmt_iso

_ALPHABET = string.ascii_lowercase + string.digits

PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0


def _request_id():
    return "req_" + "".join(random.choice(_ALPHABET) for _ in range(16))


def _meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": fmt_iso(datetime.now(timezone.utc)),
    }


def object_response(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def array_response(items, total_count, limit, offset, status=200):
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
