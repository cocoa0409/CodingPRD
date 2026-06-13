"""Standard response envelope helpers.

Envelope format is fixed by PRD Section 2.2 / SCAFFOLD 1.0:
  success: { "meta": { "api_request_id", "api_request_timestamp", [pagination] },
             "response_type": "object" | "array", "data": {...} }
  error:   { "meta": { "api_request_id", "api_request_timestamp" },
             "response_type": "error",
             "data": { "error_id", "message" } }
"""
import random
import string

from flask import jsonify

from clock import now_iso


def _request_id():
    # "api_request_id ... starts with req_" (PRD 2.2)
    alnum = string.ascii_uppercase + string.ascii_lowercase + string.digits
    return "req_" + "".join(random.choice(alnum) for _ in range(20))


def _meta(extra=None):
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": now_iso(),
    }
    if extra:
        meta.update(extra)
    return meta


def object_response(data, status=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": data if data is not None else {},
    }
    return jsonify(body), status


def array_response(items, limit, offset, total_count, status=200):
    # Pagination fields live in meta (PRD 2.3: limit, offset, total_count, has_more)
    has_more = (offset + len(items)) < total_count
    pag = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": has_more,
    }
    body = {
        "meta": _meta(pag),
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), status


def error_response(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message,
        },
    }
    return jsonify(body), status
