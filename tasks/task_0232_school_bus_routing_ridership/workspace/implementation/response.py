"""Standard response envelope helpers (PRD §2.2, SCAFFOLD §1.0)."""

from flask import jsonify
from db import new_request_id, iso_now


def _meta(extra=None):
    meta = {
        "api_request_id": new_request_id(),
        "api_request_timestamp": iso_now(),
    }
    if extra:
        meta.update(extra)
    return meta


def ok(data, status=200):
    """Single-object success envelope."""
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": data if data is not None else {},
    }
    return jsonify(body), status


def ok_list(items, limit, offset, total_count):
    """Array success envelope with pagination meta fields."""
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
    return jsonify(body), 200


def error_body(error_id, message):
    """Error envelope (4xx/412)."""
    return {
        "meta": _meta(),
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message,
        },
    }
