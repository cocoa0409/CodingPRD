"""Shared helpers: envelope, timestamps, pagination, body validation."""

import re
import secrets
import string
from datetime import datetime, timezone

from flask import jsonify, request

from db import store
from errors import ApiError

def render_ts(dt):
    """ISO 8601 UTC with exactly three fractional digits, e.g. 2026-08-01T00:00:00.000Z."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    base = dt.strftime("%Y-%m-%dT%H:%M:%S")
    return "%s.%03dZ" % (base, dt.microsecond // 1000)


def parse_ts(value, field):
    """Parse an ISO-8601 datetime string into an aware UTC datetime."""
    if not isinstance(value, str):
        raise ApiError("ERR_INVALID_REQUEST", "Field '%s' must be an ISO 8601 datetime string" % field)
    s = value.strip()
    try:
        if s.endswith("Z") or s.endswith("z"):
            dt = datetime.fromisoformat(s[:-1] + "+00:00")
        else:
            dt = datetime.fromisoformat(s)
    except ValueError:
        raise ApiError("ERR_INVALID_REQUEST", "Field '%s' is not a valid ISO 8601 datetime" % field)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def request_id():
    return "req_" + "".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(20))


def success_object(data, status=200):
    body = {
        "meta": {
            "api_request_id": request_id(),
            "api_request_timestamp": render_ts(store.now()),
        },
        "response_type": "object",
        "data": data,
    }
    return jsonify(body), status


def success_list(items, limit, offset, total_count):
    body = {
        "meta": {
            "api_request_id": request_id(),
            "api_request_timestamp": render_ts(store.now()),
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": (offset + len(items)) < total_count,
        },
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), 200


def error_response(err):
    body = {
        "meta": {
            "api_request_id": request_id(),
            "api_request_timestamp": render_ts(store.now()),
        },
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


def get_body():
    """Parse JSON body; absent/unparseable body is treated as {} (endpoints that
    require fields will fail field validation with ERR_INVALID_REQUEST)."""
    if not request.data:
        return {}
    data = request.get_json(silent=True)
    if data is None:
        raise ApiError("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    if not isinstance(data, dict):
        raise ApiError("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    return data


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def is_number(v):
    return (isinstance(v, (int, float)) and not isinstance(v, bool))


def req_str(body, field):
    v = body.get(field)
    if not isinstance(v, str) or v == "":
        raise ApiError("ERR_INVALID_REQUEST", "Field '%s' is required and must be a non-empty string" % field)
    return v


def opt_str(body, field):
    v = body.get(field)
    if v is None:
        return None
    if not isinstance(v, str):
        raise ApiError("ERR_INVALID_REQUEST", "Field '%s' must be a string" % field)
    return v


def req_int(body, field):
    v = body.get(field)
    if not is_int(v):
        raise ApiError("ERR_INVALID_REQUEST", "Field '%s' is required and must be an integer" % field)
    return v


def req_number(body, field):
    v = body.get(field)
    if not is_number(v):
        raise ApiError("ERR_INVALID_REQUEST", "Field '%s' is required and must be a number" % field)
    return v


def req_ts(body, field):
    return parse_ts(body.get(field), field)


EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def pagination_params():
    """limit: default 10, min 1, max 100; offset: default 0."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", "Query parameter 'limit' must be an integer")
        if str(limit) != raw_limit.strip() and not (raw_limit.strip().lstrip("+").isdigit()):
            raise ApiError("ERR_INVALID_REQUEST", "Query parameter 'limit' must be an integer")
        if limit < 1 or limit > 100:
            raise ApiError("ERR_INVALID_REQUEST", "Query parameter 'limit' must be between 1 and 100")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", "Query parameter 'offset' must be an integer")
        if offset < 0:
            raise ApiError("ERR_INVALID_REQUEST", "Query parameter 'offset' must be >= 0")
    return limit, offset


def sort_rows(rows):
    """Default list ordering: created_at ascending (insertion order tie-break)."""
    return sorted(rows, key=lambda r: (r["created_at"], r.get("_seq", 0)))
