"""Response envelope helpers (PRD §2.2, §2.3)."""

from flask import jsonify, request

import store
from errors import fail


def _meta(extra=None):
    meta = {
        "api_request_id": store.request_id(),
        "api_request_timestamp": store.wall_now_iso(),
    }
    if extra:
        meta.update(extra)
    return meta


def ok(data, status=200):
    return jsonify({
        "meta": _meta(),
        "response_type": "object",
        "data": data if data is not None else {},
    }), status


def created(data):
    return ok(data, 201)


def empty():
    return ok({}, 200)


def listing(items, limit, offset, total_count):
    meta = _meta({
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": offset + len(items) < total_count,
    })
    return jsonify({
        "meta": meta,
        "response_type": "array",
        "data": items,
    }), 200


def error_body(error_id, message):
    return {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }


def pagination():
    """Parse and validate limit/offset (PRD §2.3)."""
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    limit = 10
    offset = 0
    if limit_raw is not None and limit_raw != "":
        try:
            limit = int(str(limit_raw).strip())
        except (TypeError, ValueError):
            fail("ERR_VALIDATION", "limit must be an integer")
        if limit < 1 or limit > 100:
            fail("ERR_VALIDATION", "limit must be between 1 and 100")
    if offset_raw is not None and offset_raw != "":
        try:
            offset = int(str(offset_raw).strip())
        except (TypeError, ValueError):
            fail("ERR_VALIDATION", "offset must be an integer")
        if offset < 0:
            fail("ERR_VALIDATION", "offset must be >= 0")
    return limit, offset


def paginate(records, serializer):
    limit, offset = pagination()
    total = len(records)
    page = records[offset:offset + limit]
    return listing([serializer(r) for r in page], limit, offset, total)
