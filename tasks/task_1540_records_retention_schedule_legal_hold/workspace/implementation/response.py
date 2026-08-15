"""Standard response envelope helpers, per scaffold response_envelope:

success: { "meta": {api_request_id, api_request_timestamp[, pagination]},
           "response_type": "object"|"array", "data": ... }
error:   { "meta": {api_request_id, api_request_timestamp},
           "response_type": "error", "data": {error_id, message} }

Pagination fields: limit, offset, total_count, has_more.
Defaults: limit=10 (min 1, max 100), offset=0.
"""
import secrets
from flask import jsonify

from db import now
from utils import fmt_ts


def _request_id():
    return "req_" + secrets.token_hex(11)


def _meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": fmt_ts(now()),
    }


def success_object(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def success_empty(status=200):
    body = {"meta": _meta(), "response_type": "object", "data": {}}
    return jsonify(body), status


def success_list(items, limit, offset, total_count, status=200):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), status


def error_response(error_id, http_status, message):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), http_status


def parse_pagination(args):
    """Read limit/offset query params; clamp into declared bounds."""
    try:
        limit = int(args.get("limit", 10))
    except (TypeError, ValueError):
        limit = 10
    try:
        offset = int(args.get("offset", 0))
    except (TypeError, ValueError):
        offset = 0
    limit = max(1, min(100, limit))
    offset = max(0, offset)
    return limit, offset


def paginate(items, args):
    """Sort by created_at ascending (stable: insertion order breaks ties),
    then window by limit/offset."""
    limit, offset = parse_pagination(args)
    ordered = sorted(items, key=lambda e: e["created_at"])
    total = len(ordered)
    window = ordered[offset:offset + limit]
    return window, limit, offset, total
