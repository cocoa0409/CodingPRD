"""Response envelope helpers (SCAFFOLD response_envelope / PRD section 2.2).

Success: {"meta": {"api_request_id", "api_request_timestamp", [pagination]},
          "response_type": "object"|"array", "data": ...}
Error:   {"meta": {"api_request_id", "api_request_timestamp"},
          "response_type": "error", "data": {"error_id", "message"}}
Pagination fields: limit, offset, total_count, has_more (defaults 10/0, min 1, max 100).
"""
import uuid

from flask import jsonify, request

from db import store
from util import fmt_ts


def _meta():
    return {
        "api_request_id": "req_" + uuid.uuid4().hex[:24],
        "api_request_timestamp": fmt_ts(store.clock),
    }


def success_object(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def success_list(items, total_count, limit, offset):
    m = _meta()
    m["limit"] = limit
    m["offset"] = offset
    m["total_count"] = total_count
    m["has_more"] = (offset + len(items)) < total_count
    return jsonify({"meta": m, "response_type": "array", "data": items}), 200


def error_response(error_id, http_status, message):
    return jsonify({
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }), http_status


def pagination_params():
    """limit/offset query params with defaults 10/0; limit clamped to [1, 100]."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    try:
        limit = int(raw_limit) if raw_limit is not None else 10
    except (TypeError, ValueError):
        limit = 10
    try:
        offset = int(raw_offset) if raw_offset is not None else 0
    except (TypeError, ValueError):
        offset = 0
    limit = max(1, min(100, limit))
    offset = max(0, offset)
    return limit, offset


def list_response(entities, serializer, sort_key=None):
    """Sort (creation timestamp ascending by default), paginate, serialize."""
    key = sort_key or (lambda e: (e["created_at"], e["_seq"]))
    ordered = sorted(entities, key=key)
    limit, offset = pagination_params()
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return success_list([serializer(e) for e in page], total, limit, offset)
