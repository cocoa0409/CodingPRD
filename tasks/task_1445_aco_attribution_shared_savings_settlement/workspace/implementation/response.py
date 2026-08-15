"""Response envelope helpers (SCAFFOLD section 1.0 / PRD section 2.2).

Success: {"meta": {"api_request_id", "api_request_timestamp", [pagination]},
          "response_type": "object"|"array", "data": ...}
Error:   {"meta": {"api_request_id", "api_request_timestamp"},
          "response_type": "error", "data": {"error_id", "message"}}
Pagination fields in meta: limit, offset, total_count, has_more.
"""
from flask import jsonify, request

import db
from errors import ApiError, ERR_INVALID_REQUEST


def success(data, status=200, response_type="object", pagination=None):
    meta = {
        "api_request_id": db.new_request_id(),
        "api_request_timestamp": db.next_timestamp(),
    }
    if pagination is not None:
        meta.update(pagination)
    body = {"meta": meta, "response_type": response_type, "data": data}
    return jsonify(body), status


def error(error_id, http_status, message):
    body = {
        "meta": {
            "api_request_id": db.new_request_id(),
            "api_request_timestamp": db.next_timestamp(),
        },
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), http_status


def parse_pagination():
    """limit: default 10, min 1, max 100. offset: default 0, min 0."""
    limit = 10
    offset = 0
    raw_limit = request.args.get("limit")
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise ApiError(ERR_INVALID_REQUEST, 400, "limit must be an integer")
        if limit < 1 or limit > 100:
            raise ApiError(ERR_INVALID_REQUEST, 400, "limit must be between 1 and 100")
    raw_offset = request.args.get("offset")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise ApiError(ERR_INVALID_REQUEST, 400, "offset must be an integer")
        if offset < 0:
            raise ApiError(ERR_INVALID_REQUEST, 400, "offset must be >= 0")
    return limit, offset


def list_success(items):
    limit, offset = parse_pagination()
    total = len(items)
    page = items[offset:offset + limit]
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + len(page)) < total,
    }
    return success(page, 200, "array", pagination)
