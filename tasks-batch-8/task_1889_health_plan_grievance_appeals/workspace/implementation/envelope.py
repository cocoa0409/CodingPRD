"""Response envelope helpers (scaffold response_envelope / PRD section 2.2)."""

from flask import jsonify

import db


def _meta_base():
    return {
        "api_request_id": db.new_request_id(),
        "api_request_timestamp": db.fmt_ts(db.clock_now()),
    }


def success_object(data, status=200):
    body = {
        "meta": _meta_base(),
        "response_type": "object",
        "data": data,
    }
    return jsonify(body), status


def success_list(items, total_count, limit, offset, status=200):
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
    return jsonify(body), status


def error_response(err):
    body = {
        "meta": _meta_base(),
        "response_type": "error",
        "data": {
            "error_id": err.error_id,
            "message": err.message,
        },
    }
    return jsonify(body), err.http_status


def parse_pagination(args):
    """limit / offset per PRD section 2.3 (defaults 10 / 0, limit clamped 1..100)."""
    raw_limit = args.get("limit")
    raw_offset = args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            from errors import validation
            raise validation("limit must be an integer")
        if limit < 1:
            limit = 1
        if limit > 100:
            limit = 100
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            from errors import validation
            raise validation("offset must be an integer")
        if offset < 0:
            offset = 0
    return limit, offset


def paginate(rows, limit, offset):
    total = len(rows)
    page = rows[offset:offset + limit]
    return page, total


def parse_bool_param(args, name):
    """Optional boolean query filter; None when absent or unrecognized."""
    raw = args.get(name)
    if raw is None:
        return None
    low = raw.strip().lower()
    if low == "true":
        return True
    if low == "false":
        return False
    return None
