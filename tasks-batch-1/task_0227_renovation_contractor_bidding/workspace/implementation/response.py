"""Standard response envelope helpers (PRD §2.2)."""
import random
import string

from flask import jsonify

import db


def _request_id():
    alphanum = string.ascii_letters + string.digits
    return "req_" + "".join(random.choices(alphanum, k=20))


def _meta(extra=None):
    m = {
        "api_request_id": _request_id(),
        "api_request_timestamp": db.iso_now(),
    }
    if extra:
        m.update(extra)
    return m


def success(data, status=200):
    """Single-object success envelope."""
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": data if data is not None else {},
    }
    return jsonify(body), status


def success_list(items, limit, offset, total_count, status=200):
    """Array success envelope with pagination fields in meta."""
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


def error(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message,
        },
    }
    return jsonify(body), status
