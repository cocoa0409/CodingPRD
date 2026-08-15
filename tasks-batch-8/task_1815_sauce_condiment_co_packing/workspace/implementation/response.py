"""Standard response envelope helpers (PRD §2.2 / §2.3).

Success: {"meta": {api_request_id, api_request_timestamp[, limit, offset,
total_count, has_more]}, "response_type": "object"|"array", "data": ...}
Error:   {"meta": {api_request_id, api_request_timestamp},
          "response_type": "error", "data": {"error_id", "message"}}
"""
import random
import string
from datetime import datetime, timezone

from flask import jsonify, request

from errors import err, ERR_INVALID_REQUEST
from util import fmt_ts


def _request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def _meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": fmt_ts(datetime.now(timezone.utc)),
    }


def success(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def success_list(items, total_count, limit, offset):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), 200


def error_body(error_id, message, http_status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), http_status


def parse_pagination():
    """limit/offset query params; defaults 10/0, limit clamped to [1, 100],
    offset clamped to >= 0 (PRD §2.3)."""
    raw_limit = request.args.get("limit", None)
    raw_offset = request.args.get("offset", None)
    try:
        limit = int(raw_limit) if raw_limit is not None else 10
    except (TypeError, ValueError):
        raise err(ERR_INVALID_REQUEST, 400, "limit must be an integer")
    try:
        offset = int(raw_offset) if raw_offset is not None else 0
    except (TypeError, ValueError):
        raise err(ERR_INVALID_REQUEST, 400, "offset must be an integer")
    if isinstance(limit, bool) or isinstance(offset, bool):
        raise err(ERR_INVALID_REQUEST, 400, "limit/offset must be integers")
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    return limit, offset


def paginate(items):
    """Items must already be sorted (created_at ascending). Returns a Flask response."""
    limit, offset = parse_pagination()
    total = len(items)
    return success_list(items[offset:offset + limit], total, limit, offset)
