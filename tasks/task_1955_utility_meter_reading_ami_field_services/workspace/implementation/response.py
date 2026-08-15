"""Standard response envelope helpers (meta/response_type/data)."""
import uuid
from datetime import datetime, timezone

from flask import jsonify, request

from errors import ApiError, ERR_INVALID_REQUEST
from util import fmt_dt


def _meta():
    return {
        "api_request_id": "req_" + uuid.uuid4().hex[:24],
        "api_request_timestamp": fmt_dt(datetime.now(timezone.utc)),
    }


def success(data, response_type="object", code=200, pagination=None):
    body = {"meta": _meta(), "response_type": response_type, "data": data}
    if pagination is not None:
        body["meta"].update(pagination)
    return jsonify(body), code


def error_body(error_id, message):
    return {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }


def error_resp(err):
    return jsonify(error_body(err.error_id, err.message)), err.http_status


def paginate(items):
    """Apply limit/offset query params; returns (page, pagination_meta).

    limit: default 10, min 1, max 100 (out-of-range clamped); offset default 0
    (negative clamped to 0). Non-numeric values are a 400 request error.
    """
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    try:
        limit = int(raw_limit) if raw_limit is not None else 10
    except (TypeError, ValueError):
        raise ApiError(ERR_INVALID_REQUEST, "limit must be an integer", 400)
    try:
        offset = int(raw_offset) if raw_offset is not None else 0
    except (TypeError, ValueError):
        raise ApiError(ERR_INVALID_REQUEST, "offset must be an integer", 400)
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    total = len(items)
    page = items[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(page) < total,
    }
    return page, meta


def list_response(items):
    page, meta = paginate(items)
    return success(page, response_type="array", code=200, pagination=meta)


def created_sorted(items):
    """Default list ordering: created_at ascending (insertion order breaks ties)."""
    return sorted(items, key=lambda r: (r["created_at"], r["_seq"]))
