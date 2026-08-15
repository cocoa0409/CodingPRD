"""Standard response envelope (PRD section 2.2 / 2.3)."""

import uuid

from flask import jsonify, request

import db
from errors import raise_err, ERR_INVALID_REQUEST


def _meta():
    return {
        "api_request_id": "req_" + uuid.uuid4().hex[:24],
        "api_request_timestamp": db.now_iso(),
    }


def ok(data, status=200, pagination=None):
    body = {
        "meta": _meta(),
        "response_type": "array" if isinstance(data, list) else "object",
        "data": data,
    }
    if pagination:
        body["meta"].update(pagination)
    resp = jsonify(body)
    resp.status_code = status
    return resp


def error_body(error_id, message):
    return {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }


def pagination_params():
    """Read limit/offset query params with defaults 10/0, min 1, max 100.
    Invalid values are request-shape errors (ERR_INVALID_REQUEST)."""
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    if limit_raw is None:
        limit = 10
    elif limit_raw.isdigit():
        limit = int(limit_raw)
    else:
        raise_err(ERR_INVALID_REQUEST, "limit must be an integer")
    if not (1 <= limit <= 100):
        raise_err(ERR_INVALID_REQUEST, "limit must be between 1 and 100")
    if offset_raw is None:
        offset = 0
    elif offset_raw.isdigit():
        offset = int(offset_raw)
    else:
        raise_err(ERR_INVALID_REQUEST, "offset must be an integer")
    if offset < 0:
        raise_err(ERR_INVALID_REQUEST, "offset must be >= 0")
    return limit, offset


def paginated(items):
    """Items pre-sorted by creation order; returns (page, pagination meta)."""
    limit, offset = pagination_params()
    total = len(items)
    page = items[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + limit) < total,
    }
    return page, meta
