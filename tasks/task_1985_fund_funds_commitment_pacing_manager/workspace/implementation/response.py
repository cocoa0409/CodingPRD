"""Standard response envelope (PRD 2.2 / 2.3)."""

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
    """limit/offset with defaults 10/0, min 1, max 100 (scaffold envelope)."""
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise_err(ERR_INVALID_REQUEST, "limit must be an integer")
    if not (1 <= limit <= 100):
        raise_err(ERR_INVALID_REQUEST, "limit must be between 1 and 100")
    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise_err(ERR_INVALID_REQUEST, "offset must be an integer")
    if offset < 0:
        raise_err(ERR_INVALID_REQUEST, "offset must be >= 0")
    return limit, offset


def paginated(items):
    """Items pre-sorted by created_at ASC; returns (page, pagination meta)."""
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


def list_response(items, filters=None):
    """Filter dicts by exact-match query filters, sort created_at ASC
    (tie-break insertion seq), paginate, and return the ok() response."""
    rows = list(items)
    if filters:
        for field, wanted in filters.items():
            if wanted is not None:
                rows = [r for r in rows if str(r.get(field)) == str(wanted)]
    rows.sort(key=lambda r: (r.get("created_at", ""), r.get("_seq", 0)))
    page, meta = paginated(rows)
    return ok([db.public(r) for r in page], pagination=meta)
