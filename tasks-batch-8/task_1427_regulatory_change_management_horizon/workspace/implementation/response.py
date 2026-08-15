"""Standard response envelope helpers (PRD §2.2, §2.3).

Success: { "meta": {api_request_id, api_request_timestamp, [pagination]},
           "response_type": "object" | "array", "data": ... }
Error:   { "meta": {api_request_id, api_request_timestamp},
           "response_type": "error", "data": {error_id, message} }
"""

import secrets
import string

from flask import jsonify, request

from db import wall_timestamp
from errors import ApiError, invalid_request

_ALPHABET = string.ascii_letters + string.digits


def _request_id():
    return "req_" + "".join(secrets.choice(_ALPHABET) for _ in range(22))


def success_object(data, status=200):
    body = {
        "meta": {
            "api_request_id": _request_id(),
            "api_request_timestamp": wall_timestamp(),
        },
        "response_type": "object",
        "data": data,
    }
    return jsonify(body), status


def success_list(items, total_count, limit, offset, status=200):
    has_more = (offset + len(items)) < total_count
    body = {
        "meta": {
            "api_request_id": _request_id(),
            "api_request_timestamp": wall_timestamp(),
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": has_more,
        },
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), status


def error_response(err):
    body = {
        "meta": {
            "api_request_id": _request_id(),
            "api_request_timestamp": wall_timestamp(),
        },
        "response_type": "error",
        "data": {
            "error_id": err.error_id,
            "message": err.message,
        },
    }
    return jsonify(body), err.http_status


# ---------------------------------------------------------------------------
# Pagination (PRD §2.3): limit default 10, min 1, max 100; offset default 0.
# Out-of-range values are clamped to the documented bounds.
# ---------------------------------------------------------------------------


def pagination_params():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit = 10
    offset = 0
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise invalid_request("limit must be an integer")
        if isinstance(limit, bool):
            raise invalid_request("limit must be an integer")
        if limit < 1:
            limit = 1
        if limit > 100:
            limit = 100
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise invalid_request("offset must be an integer")
        if offset < 0:
            offset = 0
    return limit, offset


def paginate(items, serializer=None):
    """Sort-stable pagination helper for list endpoints.

    `items` must already be filtered and sorted (created_at ASC); returns the
    Flask response tuple.
    """
    limit, offset = pagination_params()
    total = len(items)
    page = items[offset:offset + limit]
    if serializer is not None:
        page = [serializer(x) for x in page]
    return success_list(page, total, limit, offset)


def api_error(status, error_id, message):
    return error_response(ApiError(error_id, status, message))
