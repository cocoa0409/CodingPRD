"""Response envelope helpers (SCAFFOLD §1.0 / PRD §2.2, §2.3).

Success: {"meta": {"api_request_id", "api_request_timestamp", [pagination]},
          "response_type": "object"|"array", "data": ...}
Error:   {"meta": {"api_request_id", "api_request_timestamp"},
          "response_type": "error", "data": {"error_id", "message"}}
Pagination params: limit (default 10, min 1, max 100), offset (default 0);
list meta gains limit, offset, total_count, has_more.
"""
import uuid

from flask import jsonify, request

from timeutil import now_iso


def _meta(pagination=None):
    m = {
        "api_request_id": "req_" + uuid.uuid4().hex[:20],
        "api_request_timestamp": now_iso(),
    }
    if pagination is not None:
        m.update(pagination)
    return m


def _respond(body, status):
    resp = jsonify(body)
    resp.status_code = status
    return resp


def success(data, status=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": data,
    }
    return _respond(body, status)


def success_list(items, pagination):
    body = {
        "meta": _meta(pagination),
        "response_type": "array",
        "data": items,
    }
    return _respond(body, 200)


def error(error_id, http_status, message):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return _respond(body, http_status)


def pagination_params():
    """Read limit/offset query params with defaults and clamping (PRD §2.3)."""
    try:
        limit = int(request.args.get("limit", 10))
    except (TypeError, ValueError):
        limit = 10
    try:
        offset = int(request.args.get("offset", 0))
    except (TypeError, ValueError):
        offset = 0
    limit = max(1, min(100, limit))
    offset = max(0, offset)
    return limit, offset


def paginate(rows):
    """Slice a pre-sorted row list and build the pagination meta block."""
    limit, offset = pagination_params()
    total = len(rows)
    page = rows[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + len(page)) < total,
    }
    return page, meta
