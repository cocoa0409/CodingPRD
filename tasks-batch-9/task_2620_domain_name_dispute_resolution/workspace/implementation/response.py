"""Standard response envelope helpers."""

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
        "api_request_timestamp": db.now_str(),
    }
    if extra:
        meta.update(extra)
    return meta


def ok(data, status=200):
    """Single-object success envelope."""
    return jsonify({
        "meta": _meta(),
        "response_type": "object",
        "data": data,
    }), status


def ok_list(items, limit, offset, total_count, status=200):
    """Collection success envelope -- pagination lives inside meta."""
    return jsonify({
        "meta": _meta({
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": offset + len(items) < total_count,
        }),
        "response_type": "array",
        "data": items,
    }), status


def fail(error_id, message, status):
    return jsonify({
        "meta": _meta(),
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message,
        },
    }), status


def paginate(rows, limit, offset):
    """Apply the offset window to an already-ordered row list."""
    total = len(rows)
    return rows[offset:offset + limit], total
