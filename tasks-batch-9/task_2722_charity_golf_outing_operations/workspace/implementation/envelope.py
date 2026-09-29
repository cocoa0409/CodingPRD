"""Response envelope helpers (PRD section 2.2 / 2.3)."""

from datetime import datetime, timezone

from flask import jsonify

from errors import ApiError
from store import fmt_ts, request_id

PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0


def _meta():
    return {
        "api_request_id": request_id(),
        "api_request_timestamp": fmt_ts(datetime.now(timezone.utc)),
    }


def ok(data, code=200):
    body = {"meta": _meta(), "response_type": "object", "data": data if data is not None else {}}
    return jsonify(body), code


def created(data):
    return ok(data, 201)


def ok_list(rows, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(rows)) < total_count
    body = {"meta": meta, "response_type": "array", "data": rows}
    return jsonify(body), 200


def error_response(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


def paginate(rows, limit, offset, serializer):
    total = len(rows)
    window = rows[offset: offset + limit]
    return ok_list([serializer(r) for r in window], limit, offset, total)
