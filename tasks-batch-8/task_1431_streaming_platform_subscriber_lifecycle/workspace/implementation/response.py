"""Standard response envelope helpers per SCAFFOLD §1.0 / PRD §2.2."""
import uuid
from datetime import datetime, timezone
from flask import jsonify

from errors import ApiError


def _request_id():
    return "req_" + uuid.uuid4().hex[:24]


def _request_timestamp():
    # ISO 8601 UTC with 3 fractional digits
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def success_object(data, http_code=200):
    body = {
        "meta": {
            "api_request_id": _request_id(),
            "api_request_timestamp": _request_timestamp(),
        },
        "response_type": "object",
        "data": data,
    }
    return jsonify(body), http_code


def success_list(items, limit, offset, total_count):
    has_more = (offset + len(items)) < total_count
    body = {
        "meta": {
            "api_request_id": _request_id(),
            "api_request_timestamp": _request_timestamp(),
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": has_more,
        },
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), 200


def error_response(api_error):
    body = {
        "meta": {
            "api_request_id": _request_id(),
            "api_request_timestamp": _request_timestamp(),
        },
        "response_type": "error",
        "data": {
            "error_id": api_error.error_id,
            "message": api_error.message,
        },
    }
    return jsonify(body), api_error.http_status


def parse_pagination(args):
    """Parse limit/offset with defaults from SCAFFOLD: limit=10, min=1, max=100, offset=0."""
    limit_raw = args.get("limit")
    offset_raw = args.get("offset")
    limit = 10
    offset = 0
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", 400, "limit must be an integer")
    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", 400, "offset must be an integer")
    if limit < 1 or limit > 100:
        raise ApiError("ERR_INVALID_REQUEST", 400, "limit out of range")
    if offset < 0:
        raise ApiError("ERR_INVALID_REQUEST", 400, "offset must be >= 0")
    return limit, offset


def paginate(items, args):
    """Sort by created_at ascending, then paginate."""
    limit, offset = parse_pagination(args)
    sorted_items = sorted(items, key=lambda x: x.get("created_at", ""))
    total = len(sorted_items)
    page = sorted_items[offset:offset + limit]
    return success_list(page, limit, offset, total)
