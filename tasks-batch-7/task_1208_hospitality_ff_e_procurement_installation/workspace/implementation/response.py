"""Standard response envelope helpers (PRD section 2.2 / 2.3)."""
import random
import string

from flask import jsonify, request

import db
from errors import ApiError


def _meta():
    return {
        "api_request_id": "req_" + "".join(
            random.choices(string.ascii_letters + string.digits, k=20)
        ),
        "api_request_timestamp": db.now_ts(),
    }


def ok(data, code=200, pagination=None):
    body = {
        "meta": _meta(),
        "response_type": "array" if isinstance(data, list) else "object",
        "data": data,
    }
    if pagination is not None:
        body["meta"].update(pagination)
    return jsonify(body), code


def error_response(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


def paginate(rows):
    """limit (default 10, min 1, max 100) and offset (default 0) query params."""
    limit = 10
    offset = 0
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise ApiError(
                "ERR_INVALID_REQUEST", "limit must be an integer"
            )
        if limit < 1:
            limit = 1
        if limit > 100:
            limit = 100
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise ApiError(
                "ERR_INVALID_REQUEST", "offset must be an integer"
            )
        if offset < 0:
            offset = 0
    total = len(rows)
    page = rows[offset : offset + limit]
    return page, {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
