"""Standard response envelope helpers (PRD §2.2).

Success: { "meta": {...}, "response_type": "object"|"array", "data": ... }
Error:   { "meta": {...}, "response_type": "error",
           "data": { "error_id": ..., "message": ... } }
"""
import random
import string

from flask import jsonify

import clock
from timeutil import iso_z


def _request_id():
    # api_request_id is a server-generated unique identifier starting with req_.
    alphabet = string.ascii_letters + string.digits
    return "req_" + "".join(random.choices(alphabet, k=20))


def _base_meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": iso_z(clock.now()),
    }


def object_response(data, status=200):
    body = {
        "meta": _base_meta(),
        "response_type": "object",
        "data": data if data is not None else {},
    }
    return jsonify(body), status


def array_response(items, limit, offset, total_count, status=200):
    meta = _base_meta()
    # Pagination-related fields appear in meta for list endpoints.
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {
        "meta": meta,
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), status


def error_response(error_id, message, status):
    body = {
        "meta": _base_meta(),
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message,
        },
    }
    return jsonify(body), status
