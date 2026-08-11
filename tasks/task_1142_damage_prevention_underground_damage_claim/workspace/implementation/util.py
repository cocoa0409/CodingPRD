"""Shared helpers: ids, timestamps, parsing, response envelope, pagination."""

import random
import string
import uuid
from datetime import datetime, timezone

from flask import request

from errors import err_invalid_request


def new_id():
    return str(uuid.uuid4())


def now_ts():
    """Response envelope timestamp: ISO 8601 UTC with three fractional digits."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + \
        f"{datetime.now(timezone.utc).microsecond // 1000:03d}Z"


def fmt_dt(dt):
    """Format a datetime as ISO 8601 UTC with three fractional digits, Z suffix."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def new_request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def parse_dt(value, field="datetime"):
    """Parse an ISO 8601 datetime. Accepts trailing Z or offset."""
    if not isinstance(value, str):
        raise err_invalid_request(f"{field} must be an ISO 8601 string")
    s = value.strip()
    try:
        if s.endswith("Z"):
            s2 = s[:-1] + "+00:00"
        else:
            s2 = s
        dt = datetime.fromisoformat(s2)
    except Exception:
        raise err_invalid_request(f"malformed datetime: {field}")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_body(required_fields=(), optional_fields=()):
    if not request.is_json:
        body = request.get_json(silent=True)
        if body is None:
            body = {}
    else:
        body = request.get_json(silent=True) or {}
    if not isinstance(body, dict):
        raise err_invalid_request("request body must be a JSON object")
    for f in required_fields:
        if f not in body or body.get(f) is None:
            raise err_invalid_request(f"missing required field: {f}")
    return body


def success_envelope(data, response_type="object", status=200, pagination=None):
    meta = {
        "api_request_id": new_request_id(),
        "api_request_timestamp": now_ts(),
    }
    if pagination is not None:
        meta["limit"] = pagination["limit"]
        meta["offset"] = pagination["offset"]
        meta["total_count"] = pagination["total_count"]
        meta["has_more"] = pagination["has_more"]
    body = {
        "meta": meta,
        "response_type": response_type,
        "data": data,
    }
    return body, status


def error_envelope(error_id, message):
    body = {
        "meta": {
            "api_request_id": new_request_id(),
            "api_request_timestamp": now_ts(),
        },
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message,
        },
    }
    return body


def get_pagination():
    """limit: default 10, min 1, max 100. offset: default 0, min 0."""
    args = request.args
    limit_raw = args.get("limit")
    offset_raw = args.get("offset")
    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except Exception:
            raise err_invalid_request("limit must be an integer")
        if limit < 1:
            raise err_invalid_request("limit must be at least 1")
        if limit > 100:
            limit = 100
    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except Exception:
            raise err_invalid_request("offset must be an integer")
        if offset < 0:
            raise err_invalid_request("offset must be non-negative")
    return limit, offset


def paginate(items, limit, offset):
    """items must already be sorted. Returns (page, pagination_meta)."""
    total = len(items)
    page = items[offset:offset + limit]
    has_more = (offset + limit) < total
    return page, {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": has_more,
    }


def require_enum(value, allowed, field):
    if value not in allowed:
        raise err_invalid_request(f"invalid enum member for {field}: {value}")
    return value


def require_int(value, field):
    if isinstance(value, bool) or not isinstance(value, int):
        raise err_invalid_request(f"{field} must be an integer")
    return value


def require_number(value, field):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise err_invalid_request(f"{field} must be a number")
    return value


def require_positive_int(value, field):
    require_int(value, field)
    if value <= 0:
        raise err_invalid_request(f"{field} must be > 0")
    return value


def require_positive_number(value, field):
    require_number(value, field)
    if value <= 0:
        raise err_invalid_request(f"{field} must be > 0")
    return value


def require_string(value, field):
    if not isinstance(value, str):
        raise err_invalid_request(f"{field} must be a string")
    return value
