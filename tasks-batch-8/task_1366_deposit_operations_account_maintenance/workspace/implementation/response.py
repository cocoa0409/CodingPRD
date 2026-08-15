"""Response envelope helpers (PRD §2.2, §2.3).

Success:  {"meta": {"api_request_id", "api_request_timestamp", [pagination]},
           "response_type": "object" | "array", "data": ...}
Error:    {"meta": {"api_request_id", "api_request_timestamp"},
           "response_type": "error", "data": {"error_id", "message"}}
Pagination params: limit (default 10, min 1, max 100), offset (default 0).
"""

import random
import string
from datetime import datetime, timezone

from flask import jsonify

from errors import ApiError

DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0


def _request_id() -> str:
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def _request_timestamp() -> str:
    """ISO 8601 UTC with exactly three fractional digits, e.g. 2025-05-24T10:30:00.123Z."""
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def success_object(payload, status: int = 200):
    body = {
        "meta": {
            "api_request_id": _request_id(),
            "api_request_timestamp": _request_timestamp(),
        },
        "response_type": "object",
        "data": payload,
    }
    return jsonify(body), status


def success_list(items, total_count: int, limit: int, offset: int, status: int = 200):
    body = {
        "meta": {
            "api_request_id": _request_id(),
            "api_request_timestamp": _request_timestamp(),
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": (offset + len(items)) < total_count,
        },
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), status


def error_response(err: ApiError):
    body = {
        "meta": {
            "api_request_id": _request_id(),
            "api_request_timestamp": _request_timestamp(),
        },
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


def parse_pagination(args):
    """Parse limit/offset query params; out-of-range values fail shape validation."""
    from errors import ApiError, ERR_INVALID_REQUEST

    raw_limit = args.get("limit")
    raw_offset = args.get("offset")
    limit = DEFAULT_LIMIT
    offset = DEFAULT_OFFSET
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise ApiError(ERR_INVALID_REQUEST, "limit must be an integer")
        if limit < MIN_LIMIT or limit > MAX_LIMIT:
            raise ApiError(
                ERR_INVALID_REQUEST,
                f"limit must be between {MIN_LIMIT} and {MAX_LIMIT}",
            )
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise ApiError(ERR_INVALID_REQUEST, "offset must be an integer")
        if offset < 0:
            raise ApiError(ERR_INVALID_REQUEST, "offset must be >= 0")
    return limit, offset


def paginate(items, limit: int, offset: int):
    """Slice a full (already sorted) item list per limit/offset."""
    return items[offset : offset + limit]
