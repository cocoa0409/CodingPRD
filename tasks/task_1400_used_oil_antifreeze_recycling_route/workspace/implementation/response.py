"""Standard response envelope helpers (SCAFFOLD §1.0 / PRD §2.2).

Success: {"meta": {"api_request_id", "api_request_timestamp", [pagination]},
          "response_type": "object" | "array", "data": ...}
Error:   {"meta": {"api_request_id", "api_request_timestamp"},
          "response_type": "error", "data": {"error_id", "message"}}

Pagination parameters are limit (default 10, min 1, max 100) and offset
(default 0); list responses carry limit/offset/total_count/has_more in meta.
"""

import uuid

from flask import jsonify, request

import db

PAGE_DEFAULT_LIMIT = 10
PAGE_MIN_LIMIT = 1
PAGE_MAX_LIMIT = 100
PAGE_DEFAULT_OFFSET = 0


def _meta():
    return {
        "api_request_id": "req_" + uuid.uuid4().hex[:24],
        "api_request_timestamp": db.now_iso(),
    }


def success_object(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def _parse_int_arg(name, default):
    raw = request.args.get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def pagination_params():
    limit = _parse_int_arg("limit", PAGE_DEFAULT_LIMIT)
    offset = _parse_int_arg("offset", PAGE_DEFAULT_OFFSET)
    if limit < PAGE_MIN_LIMIT:
        limit = PAGE_MIN_LIMIT
    if limit > PAGE_MAX_LIMIT:
        limit = PAGE_MAX_LIMIT
    if offset < 0:
        offset = 0
    return limit, offset


def success_list(items, status=200):
    """items must already be filtered and sorted; slicing happens here."""
    limit, offset = pagination_params()
    total = len(items)
    page = items[offset:offset + limit]
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total
    meta["has_more"] = (offset + len(page)) < total
    body = {"meta": meta, "response_type": "array", "data": page}
    return jsonify(body), status


def error_response(api_error):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": api_error.error_id, "message": api_error.message},
    }
    return jsonify(body), api_error.http_status
