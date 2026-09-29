"""Standard response envelope (PRD 2.2)."""
from flask import jsonify

from util import new_request_id, now_ts


def _meta(extra=None):
    meta = {
        "api_request_id": new_request_id(),
        "api_request_timestamp": now_ts(),
    }
    if extra:
        meta.update(extra)
    return meta


def object_response(data, status=200):
    return jsonify({
        "meta": _meta(),
        "response_type": "object",
        "data": data if data is not None else {},
    }), status


def array_response(items, status=200, page=None):
    """`page` carries the pagination fields for list endpoints."""
    return jsonify({
        "meta": _meta(page),
        "response_type": "array",
        "data": items,
    }), status


def paged_response(rows, limit, offset, status=200):
    total = len(rows)
    window = rows[offset:offset + limit]
    page = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(window) < total,
    }
    return array_response(window, status=status, page=page)


def error_response(error_id, message, status):
    return jsonify({
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }), status
