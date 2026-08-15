"""Standard response envelope helpers, matching SCAFFOLD response_envelope
and PRD §2.2."""

import random
import string
from datetime import datetime, timezone
from flask import jsonify

from db import store


def _gen_request_id():
    suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=20))
    return f"req_{suffix}"


def _now_iso_ms():
    """ISO 8601 UTC timestamp with three fractional digits."""
    n = datetime.now(timezone.utc)
    return n.strftime("%Y-%m-%dT%H:%M:%S.") + f"{n.microsecond // 1000:03d}Z"


def success_object(data, http_status=200):
    body = {
        "meta": {
            "api_request_id": _gen_request_id(),
            "api_request_timestamp": _now_iso_ms(),
        },
        "response_type": "object",
        "data": data,
    }
    return jsonify(body), http_status


def success_list(items, limit, offset, total_count, http_status=200):
    has_more = (offset + len(items)) < total_count
    body = {
        "meta": {
            "api_request_id": _gen_request_id(),
            "api_request_timestamp": _now_iso_ms(),
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": has_more,
        },
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), http_status


def error_response(error_id, http_status, message):
    body = {
        "meta": {
            "api_request_id": _gen_request_id(),
            "api_request_timestamp": _now_iso_ms(),
        },
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message,
        },
    }
    return jsonify(body), http_status


def parse_pagination(args):
    """Parse limit/offset from query params per scaffold defaults."""
    limit_s = args.get("limit")
    offset_s = args.get("offset")
    limit = 10
    offset = 0
    if limit_s is not None:
        try:
            limit = int(limit_s)
        except (TypeError, ValueError):
            from errors import invalid_request
            raise invalid_request("limit must be an integer")
        if limit < 1 or limit > 100:
            from errors import invalid_request
            raise invalid_request("limit must be between 1 and 100")
    if offset_s is not None:
        try:
            offset = int(offset_s)
        except (TypeError, ValueError):
            from errors import invalid_request
            raise invalid_request("offset must be an integer")
        if offset < 0:
            from errors import invalid_request
            raise invalid_request("offset must be >= 0")
    return limit, offset
