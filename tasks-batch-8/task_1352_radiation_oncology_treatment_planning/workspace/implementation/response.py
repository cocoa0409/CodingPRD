"""Standard response envelope helpers (PRD section 2.2 / 2.3)."""
from flask import jsonify, request

from errors import ApiError, ERR_INVALID_REQUEST, err
from timeutil import new_req_id, now_iso


def success(data, status=200, pagination=None):
    meta = {"api_request_id": new_req_id(), "api_request_timestamp": now_iso()}
    if pagination is not None:
        meta.update(pagination)
    body = {
        "meta": meta,
        "response_type": "array" if isinstance(data, list) else "object",
        "data": data,
    }
    return jsonify(body), status


def error_body(error_id, message):
    return {
        "meta": {"api_request_id": new_req_id(), "api_request_timestamp": now_iso()},
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }


def api_error_response(e):
    return jsonify(error_body(e.error_id, e.message)), e.http_status


def page_params():
    """limit/offset with scaffold defaults: limit default 10, min 1, max 100;
    offset default 0. Out-of-range values are clamped; non-numeric -> 400."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    try:
        limit = int(raw_limit) if raw_limit is not None else 10
    except (TypeError, ValueError):
        err(ERR_INVALID_REQUEST, "limit must be an integer")
    try:
        offset = int(raw_offset) if raw_offset is not None else 0
    except (TypeError, ValueError):
        err(ERR_INVALID_REQUEST, "offset must be an integer")
    limit = max(1, min(100, limit))
    offset = max(0, offset)
    return limit, offset


def paginate(items):
    """Apply pagination to an already-sorted list; returns (page, meta_fields)."""
    limit, offset = page_params()
    total = len(items)
    page = items[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + len(page)) < total,
    }
    return page, meta
