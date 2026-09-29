"""Standard response envelope (PRD section 2.2) and pagination (section 2.3)."""

from flask import jsonify, request

import store
from common import fmt_iso, new_request_id
from errors import fail


def _meta():
    return {
        "api_request_id": new_request_id(),
        "api_request_timestamp": fmt_iso(store.now()),
    }


def object_response(data, status=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": data if data is not None else {},
    }
    return jsonify(body), status


def list_response(rows, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(rows)) < total_count
    body = {
        "meta": meta,
        "response_type": "array",
        "data": rows,
    }
    return jsonify(body), 200


def error_response(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message,
        },
    }
    return jsonify(body), status


# ---------------------------------------------------------------------------
# Pagination (priority 45)
# ---------------------------------------------------------------------------

def pagination():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")

    limit = 10
    offset = 0

    if raw_limit is not None:
        try:
            limit = int(str(raw_limit).strip())
        except (TypeError, ValueError):
            fail("ERR_VALIDATION", "limit must be an integer between 1 and 100.")
        if limit < 1 or limit > 100:
            fail("ERR_VALIDATION", "limit must be between 1 and 100 inclusive.")

    if raw_offset is not None:
        try:
            offset = int(str(raw_offset).strip())
        except (TypeError, ValueError):
            fail("ERR_VALIDATION", "offset must be a non-negative integer.")
        if offset < 0:
            fail("ERR_VALIDATION", "offset may not be negative.")

    return limit, offset


def paginate(rows, limit, offset, serializer):
    total = len(rows)
    window = rows[offset: offset + limit]
    return list_response([serializer(r) for r in window], limit, offset, total)
