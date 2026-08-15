"""Standard response envelope helpers, per PRD §2.2 and §2.3."""

from flask import jsonify

from db import new_request_id, CLOCK, iso_ts
from errors import ApiError, invalid_request


def _meta():
    return {
        "api_request_id": new_request_id(),
        "api_request_timestamp": iso_ts(CLOCK.now()),
    }


def success_object(data, status=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": data,
    }
    return jsonify(body), status


def success_list(items, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {
        "meta": meta,
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), 200


def error_response(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {
            "error_id": err.error_id,
            "message": err.message,
        },
    }
    return jsonify(body), err.http_status


def parse_pagination(args):
    """Parse limit/offset per PRD §2.3: default 10, min 1, max 100, offset default 0."""
    raw_limit = args.get("limit")
    raw_offset = args.get("offset")
    limit = 10
    offset = 0
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise invalid_request("limit must be an integer")
        if limit < 1 or limit > 100:
            raise invalid_request("limit must be between 1 and 100")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise invalid_request("offset must be an integer")
        if offset < 0:
            raise invalid_request("offset must be >= 0")
    return limit, offset


def paginate(items, args):
    """Sort by created_at ascending (stable), then paginate."""
    limit, offset = parse_pagination(args)
    sorted_items = sorted(items, key=lambda r: (r.get("created_at", ""), r.get("id", "")))
    total = len(sorted_items)
    page = sorted_items[offset:offset + limit]
    return success_list(page, limit, offset, total)
