"""Shared helpers: timestamps, request body validation, pagination."""
from datetime import datetime, timezone

from flask import request

from errors import (
    ApiError,
    ERR_INVALID_REQUEST,
    ERR_INVALID_ENUM,
)

# Logical-clock startup instant per PRD §2.5.
START_UTC = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


def wall_now():
    return datetime.now(timezone.utc)


def fmt_iso(dt):
    """ISO 8601 UTC with three fractional digits, e.g. 2026-08-01T00:00:00.000Z."""
    if dt is None:
        return None
    return dt.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def parse_iso(value):
    """Tolerant ISO-8601 parser; returns aware UTC datetime or None."""
    if not isinstance(value, str) or not value.strip():
        return None
    s = value.strip()
    if s.endswith("Z") or s.endswith("z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def add_years(dt, n):
    """Calendar-year addition (Feb 29 clamps to Feb 28)."""
    try:
        return dt.replace(year=dt.year + n)
    except ValueError:
        return dt.replace(year=dt.year + n, day=28)


# ---------------------------------------------------------------------------
# Request body handling
# ---------------------------------------------------------------------------

def get_body():
    if not request.data:
        return {}
    data = request.get_json(silent=True)
    if data is None:
        raise ApiError(ERR_INVALID_REQUEST, "Request body must be valid JSON", 400)
    if not isinstance(data, dict):
        raise ApiError(ERR_INVALID_REQUEST, "Request body must be a JSON object", 400)
    return data


def req_field(body, name):
    if name not in body or body[name] is None:
        raise ApiError(ERR_INVALID_REQUEST, "Missing required field: %s" % name, 400)
    return body[name]


def req_str(body, name):
    v = req_field(body, name)
    if not isinstance(v, str) or not v:
        raise ApiError(ERR_INVALID_REQUEST, "Field %s must be a non-empty string" % name, 400)
    return v


def opt_str(body, name, default=None):
    if name not in body or body[name] is None:
        return default
    v = body[name]
    if not isinstance(v, str):
        raise ApiError(ERR_INVALID_REQUEST, "Field %s must be a string" % name, 400)
    return v


def req_int(body, name):
    v = req_field(body, name)
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError(ERR_INVALID_REQUEST, "Field %s must be an integer" % name, 400)
    return v


def opt_int(body, name, default=None):
    if name not in body or body[name] is None:
        return default
    v = body[name]
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError(ERR_INVALID_REQUEST, "Field %s must be an integer" % name, 400)
    return v


def req_bool(body, name):
    v = req_field(body, name)
    if not isinstance(v, bool):
        raise ApiError(ERR_INVALID_REQUEST, "Field %s must be a boolean" % name, 400)
    return v


def opt_bool(body, name, default=None):
    if name not in body or body[name] is None:
        return default
    v = body[name]
    if not isinstance(v, bool):
        raise ApiError(ERR_INVALID_REQUEST, "Field %s must be a boolean" % name, 400)
    return v


def req_enum(body, name, allowed):
    v = req_field(body, name)
    if not isinstance(v, str):
        raise ApiError(ERR_INVALID_REQUEST, "Field %s must be a string" % name, 400)
    if v not in allowed:
        raise ApiError(
            ERR_INVALID_ENUM,
            "Field %s value %r is not one of %s" % (name, v, sorted(allowed)),
            400,
        )
    return v


def opt_enum(body, name, allowed, default=None):
    if name not in body or body[name] is None:
        return default
    return req_enum(body, name, allowed)


def req_dt(body, name):
    v = req_field(body, name)
    dt = parse_iso(v)
    if dt is None:
        raise ApiError(ERR_INVALID_REQUEST, "Field %s must be an ISO 8601 timestamp" % name, 400)
    return dt


def req_str_array(body, name):
    v = req_field(body, name)
    if not isinstance(v, list) or not all(isinstance(x, str) for x in v):
        raise ApiError(ERR_INVALID_REQUEST, "Field %s must be an array of strings" % name, 400)
    return v


def opt_object(body, name, default=None):
    if name not in body or body[name] is None:
        return {} if default is None else default
    v = body[name]
    if not isinstance(v, dict):
        raise ApiError(ERR_INVALID_REQUEST, "Field %s must be an object" % name, 400)
    return v


# ---------------------------------------------------------------------------
# Pagination (PRD §2.3): limit default 10, min 1, max 100; offset default 0.
# ---------------------------------------------------------------------------

def pagination():
    raw_limit = request.args.get("limit", "10")
    raw_offset = request.args.get("offset", "0")
    try:
        limit = int(raw_limit)
        offset = int(raw_offset)
    except (TypeError, ValueError):
        raise ApiError(ERR_INVALID_REQUEST, "limit and offset must be integers", 400)
    if limit < 1 or limit > 100:
        raise ApiError(ERR_INVALID_REQUEST, "limit must be between 1 and 100", 400)
    if offset < 0:
        raise ApiError(ERR_INVALID_REQUEST, "offset must be >= 0", 400)
    return limit, offset
