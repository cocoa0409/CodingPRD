"""Standard response-envelope helpers.

Envelope shape is fixed by SCAFFOLD.yaml response_envelope / PRD §2.2:

  success: { "meta": {api_request_id, api_request_timestamp, [pagination]},
             "response_type": "object"|"array", "data": {...} }
  error:   { "meta": {api_request_id, api_request_timestamp},
             "response_type": "error", "data": {error_id, message} }
"""

import random
import string

from flask import jsonify

from db import now_iso


def _request_id():
    chars = string.ascii_letters + string.digits
    return "req_" + "".join(random.choices(chars, k=20))


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
    has_more = (offset + len(items)) < total_count
    body = {
        "meta": _meta({
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": has_more,
        }),
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
