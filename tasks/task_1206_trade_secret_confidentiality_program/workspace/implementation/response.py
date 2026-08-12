"""Standard response envelope (SCAFFOLD §1.0 / PRD §2.2 — verbatim shapes).

Success: {"meta": {...}, "response_type": "object"|"array", "data": ...}
Error:   {"meta": {...}, "response_type": "error", "data": {"error_id", "message"}}
List responses add limit/offset/total_count/has_more to `meta`.
"""

import uuid

from flask import jsonify

from db import fmt_ts, now
from errors import ApiError


def _meta():
    return {
        "api_request_id": "req_" + uuid.uuid4().hex[:24],
        "api_request_timestamp": fmt_ts(now()),
    }


def ok_object(data, code=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), code


def ok_list(items, limit, offset, total_count, code=200):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), code


def error_response(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


def paginate(rows, args):
    """limit/offset pagination with the scaffold's defaults (limit 10, min 1,
    max 100, offset 0). Rows must already be sorted by created_at ascending."""
    limit = _parse_int(args.get("limit"), 10)
    offset = _parse_int(args.get("offset"), 0)
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    total = len(rows)
    page = rows[offset : offset + limit]
    return page, limit, offset, total


def _parse_int(value, default):
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
