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
from errors import ApiError, invalid_pagination

_ALPHABET = string.ascii_letters + string.digits


def _request_id():
    return "req_" + "".join(secrets.choice(_ALPHABET) for _ in range(20))


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


def api_error(status, error_id, message):
    return error_response(ApiError(error_id, status, message))


# ---------------------------------------------------------------------------
# Pagination (PRD §2.3): limit default 10, bounds 1..100; offset default 0,
# min 0. Out-of-range values are REJECTED with ERR_INVALID_PAGINATION_PARAMETERS.
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
            raise invalid_pagination("limit must be an integer")
        if isinstance(limit, bool) or limit < 1 or limit > 100:
            raise invalid_pagination("limit must be within 1..100")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise invalid_pagination("offset must be an integer")
        if offset < 0:
            raise invalid_pagination("offset must be >= 0")
    return limit, offset


def paginate(items, serializer):
    """`items` must already be filtered and sorted (created_at ASC, stable by
    insertion sequence); returns the Flask response tuple."""
    limit, offset = pagination_params()
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serializer(x) for x in page], total, limit, offset)


def sort_created(items):
    """PRD §2.3 default sort: created_at ascending; stable on insertion
    sequence for same-instant creations."""
    return sorted(items, key=lambda e: (e["created_at"], e.get("_seq", 0)))
