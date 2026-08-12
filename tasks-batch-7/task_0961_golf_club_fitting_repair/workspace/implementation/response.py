"""Standard response envelope helpers and shared utilities."""
import random
import string
from datetime import datetime, timezone
from flask import jsonify

from db import db


def _gen_request_id():
    suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=20))
    return "req_" + suffix


def _now_iso():
    """Current logical-clock timestamp as ISO8601 UTC with three fractional digits."""
    dt = db.logical_now
    # Format with exactly 3 fractional digits, Z suffix
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def success_response(data, status=200, response_type="object", pagination=None):
    meta = {
        "api_request_id": _gen_request_id(),
        "api_request_timestamp": _now_iso(),
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
    resp = jsonify(body)
    resp.status_code = status
    return resp


def error_response(error_id, message, http_status):
    body = {
        "meta": {
            "api_request_id": _gen_request_id(),
            "api_request_timestamp": _now_iso(),
        },
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message,
        },
    }
    resp = jsonify(body)
    resp.status_code = http_status
    return resp


def parse_iso(value):
    """Parse an ISO8601 timestamp string into an aware datetime (UTC)."""
    if not isinstance(value, str):
        raise ValueError("not a string")
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def iso_format(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_pagination(args):
    """Parse limit/offset query params with defaults and clamping."""
    from errors import raise_err

    raw_limit = args.get("limit")
    raw_offset = args.get("offset")
    limit = 10
    offset = 0
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise_err("ERR_VALIDATION", "limit must be an integer")
        if limit < 1 or limit > 100:
            raise_err("ERR_VALIDATION", "limit out of range")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise_err("ERR_VALIDATION", "offset must be an integer")
        if offset < 0:
            raise_err("ERR_VALIDATION", "offset out of range")
    return limit, offset


def apply_pagination(items, limit, offset):
    total = len(items)
    page = items[offset:offset + limit]
    has_more = (offset + limit) < total
    return page, {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": has_more,
    }
