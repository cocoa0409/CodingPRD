"""Response envelope helpers — meta/response_type/data per scaffold §1.0."""

from flask import jsonify, request

import db
from errors import ApiError, ERR_INVALID_REQUEST


def success_object(data, status=200):
    body = {
        "meta": {
            "api_request_id": db.new_request_id(),
            "api_request_timestamp": db.now_iso(),
        },
        "response_type": "object",
        "data": data,
    }
    return jsonify(body), status


def success_list(items, total_count, limit, offset):
    body = {
        "meta": {
            "api_request_id": db.new_request_id(),
            "api_request_timestamp": db.now_iso(),
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": (offset + len(items)) < total_count,
        },
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), 200


def error_response(error_id, message, http_status):
    body = {
        "meta": {
            "api_request_id": db.new_request_id(),
            "api_request_timestamp": db.now_iso(),
        },
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message,
        },
    }
    return jsonify(body), http_status


def parse_pagination():
    """Read limit/offset query params with scaffold defaults (10/0, 1..100)."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")

    if raw_limit is None or raw_limit == "":
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise ApiError(ERR_INVALID_REQUEST, "limit must be an integer", 400)
        if limit < 1 or limit > 100:
            raise ApiError(
                ERR_INVALID_REQUEST, "limit must be between 1 and 100", 400
            )

    if raw_offset is None or raw_offset == "":
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise ApiError(ERR_INVALID_REQUEST, "offset must be an integer", 400)
        if offset < 0:
            raise ApiError(ERR_INVALID_REQUEST, "offset must be >= 0", 400)

    return limit, offset


def paginate(items, limit, offset):
    total = len(items)
    return items[offset : offset + limit], total
