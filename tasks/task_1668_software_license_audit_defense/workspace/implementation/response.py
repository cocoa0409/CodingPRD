"""Response envelope helpers (PRD §2.2, §2.3)."""

import random
import string

from flask import jsonify, request

import db
from errors import ApiError, ERR_INVALID_REQUEST


def _request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def _meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": db.now_iso(),
    }


def success_object(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def success_list(items, total_count, limit, offset, status=200):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), status


def error_response(err: ApiError):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


def parse_pagination():
    """Read limit/offset query params per PRD §2.3 (default 10, min 1, max 100)."""
    args = request.args
    raw_limit = args.get("limit")
    raw_offset = args.get("offset")
    limit = 10
    offset = 0
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise ApiError(ERR_INVALID_REQUEST, 400, "limit must be an integer")
        if limit < 1 or limit > 100:
            raise ApiError(ERR_INVALID_REQUEST, 400,
                           "limit must be between 1 and 100")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise ApiError(ERR_INVALID_REQUEST, 400, "offset must be an integer")
        if offset < 0:
            raise ApiError(ERR_INVALID_REQUEST, 400, "offset must be >= 0")
    return limit, offset


def paginate(records):
    """Sort by created_at ascending and apply limit/offset.

    Python's sort is stable, so records sharing the same logical-clock
    created_at keep their creation (insertion) order.
    """
    limit, offset = parse_pagination()
    ordered = sorted(records, key=lambda r: r["created_at"])
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return page, total, limit, offset
