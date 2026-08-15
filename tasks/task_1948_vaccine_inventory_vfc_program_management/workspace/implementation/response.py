"""Response envelope helpers per SCAFFOLD §1.0 / PRD §2.2 and §2.3."""

from flask import jsonify

import db


def _meta_base():
    return {
        "api_request_id": db.new_request_id(),
        "api_request_timestamp": db.now_ts(),
    }


def success_object(data, status_code=200):
    body = {
        "meta": _meta_base(),
        "response_type": "object",
        "data": data,
    }
    return jsonify(body), status_code


def success_list(items, limit, offset, total_count):
    meta = _meta_base()
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


def error_response(error_id, message, http_status):
    body = {
        "meta": _meta_base(),
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message,
        },
    }
    return jsonify(body), http_status


def parse_pagination(args):
    """Parse limit/offset per PRD §2.3. Returns (limit, offset) or raises ApiError."""
    from errors import invalid_request

    limit_raw = args.get("limit", None)
    offset_raw = args.get("offset", None)

    limit = 10
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise invalid_request("limit must be an integer")
        if limit < 1 or limit > 100:
            raise invalid_request("limit out of range (1..100)")

    offset = 0
    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise invalid_request("offset must be an integer")
        if offset < 0:
            raise invalid_request("offset must be >= 0")

    return limit, offset


def paginate(items, args):
    """Sort by created_at ascending, apply filters upstream, slice, and wrap."""
    limit, offset = parse_pagination(args)
    total = len(items)
    page = items[offset:offset + limit]
    return success_list(page, limit, offset, total)
