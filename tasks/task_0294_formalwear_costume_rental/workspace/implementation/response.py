"""Standard response envelope helpers.

Envelope shape (SCAFFOLD §1.0 / PRD §2.2):
    success: { "meta": { "api_request_id", "api_request_timestamp", [pagination] },
               "response_type": "object" | "array", "data": {} }
    error:   { "meta": { "api_request_id", "api_request_timestamp" },
               "response_type": "error",
               "data": { "error_id", "message" } }
"""
import random
import string

from flask import jsonify

from clock import now_iso


def _request_id():
    # api_request_id starts with "req_" followed by random alphanumerics.
    suffix = "".join(random.choices(string.ascii_letters + string.digits, k=20))
    return "req_" + suffix


def _meta(extra=None):
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": now_iso(),
    }
    if extra:
        meta.update(extra)
    return meta


def success(data, status=200, response_type="object", pagination=None):
    """Single-object or scalar success response."""
    body = {
        "meta": _meta(pagination),
        "response_type": response_type,
        "data": data if data is not None else {},
    }
    return jsonify(body), status


def list_success(items, limit, offset, total_count):
    """List/array success response with pagination bookkeeping in meta."""
    has_more = (offset + len(items)) < total_count
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": has_more,
    }
    body = {
        "meta": _meta(pagination),
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), 200


def error_response(error_id, message, http_status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message,
        },
    }
    return jsonify(body), http_status
