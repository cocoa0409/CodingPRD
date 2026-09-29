"""Standard response envelope (PRD 2.2, SCAFFOLD response_envelope).

success: { "meta": { "api_request_id", "api_request_timestamp" [, limit, offset,
           total_count, has_more] }, "response_type": "object"|"array", "data": {} }
error:   { "meta": { ... }, "response_type": "error",
           "data": { "error_id", "message" } }
"""
import random
import string

from flask import jsonify

import db

_ALPHANUM = string.ascii_uppercase + string.digits


def _request_id():
    return "req_" + "".join(random.choice(_ALPHANUM) for _ in range(20))


def _meta(extra=None):
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": db.store.now_iso(),
    }
    if extra:
        meta.update(extra)
    return meta


def object_response(data, http_status=200):
    return jsonify({
        "meta": _meta(),
        "response_type": "object",
        "data": data if data is not None else {},
    }), http_status


def array_response(items, limit, offset, total_count, http_status=200):
    return jsonify({
        "meta": _meta({
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": (offset + len(items)) < total_count,
        }),
        "response_type": "array",
        "data": items,
    }), http_status


def error_response(error_id, message, http_status):
    return jsonify({
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }), http_status
