"""Time, decimal, body-validation and pagination helpers."""
from datetime import datetime, timezone

from flask import request
from decimal import Decimal, ROUND_HALF_UP

import db
from errors import ApiError, raise_err, ERR_INVALID_REQUEST


# ---------------------------------------------------------------- time
def parse_dt(value):
    """Parse an ISO-8601 timestamp; naive values are treated as UTC."""
    if not isinstance(value, str):
        raise_err(ERR_INVALID_REQUEST, "expected ISO-8601 timestamp string")
    s = value.strip()
    try:
        dt = datetime.fromisoformat(s[:-1] + "+00:00" if s.endswith(("Z", "z")) else s)
    except ValueError:
        raise_err(ERR_INVALID_REQUEST, "invalid ISO-8601 timestamp: %r" % value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_dt(dt):
    """ISO-8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def minutes_between(a, b):
    """Whole minutes from a to b (floor of total seconds / 60)."""
    return int((b - a).total_seconds() // 60)


# ---------------------------------------------------------------- decimal
def dec(x):
    return Decimal(str(x))


def round_half_up_int(x):
    """Round a Decimal-like value half-up to a whole integer."""
    return int(dec(x).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------- body
def get_body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise_err(ERR_INVALID_REQUEST, "request body must be a JSON object")
    return data


def _present(body, name):
    return name in body and body[name] is not None


def v_str(body, name, required=True, default=None):
    if not _present(body, name):
        if required:
            raise_err(ERR_INVALID_REQUEST, "missing required field: %s" % name)
        return default
    if not isinstance(body[name], str):
        raise_err(ERR_INVALID_REQUEST, "field %s must be a string" % name)
    return body[name]


def v_int(body, name, required=True, default=None, min_value=None):
    if not _present(body, name):
        if required:
            raise_err(ERR_INVALID_REQUEST, "missing required field: %s" % name)
        return default
    v = body[name]
    if isinstance(v, bool) or not isinstance(v, int):
        raise_err(ERR_INVALID_REQUEST, "field %s must be an integer" % name)
    if min_value is not None and v < min_value:
        raise_err(ERR_INVALID_REQUEST, "field %s must be >= %s" % (name, min_value))
    return v


def v_num(body, name, required=True, default=None, min_value=None, exclusive_min=False):
    if not _present(body, name):
        if required:
            raise_err(ERR_INVALID_REQUEST, "missing required field: %s" % name)
        return default
    v = body[name]
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise_err(ERR_INVALID_REQUEST, "field %s must be a number" % name)
    if min_value is not None:
        if exclusive_min and not v > min_value:
            raise_err(ERR_INVALID_REQUEST, "field %s must be > %s" % (name, min_value))
        if not exclusive_min and v < min_value:
            raise_err(ERR_INVALID_REQUEST, "field %s must be >= %s" % (name, min_value))
    return v


def v_bool(body, name, required=False, default=None):
    if not _present(body, name):
        if required:
            raise_err(ERR_INVALID_REQUEST, "missing required field: %s" % name)
        return default
    if not isinstance(body[name], bool):
        raise_err(ERR_INVALID_REQUEST, "field %s must be a boolean" % name)
    return body[name]


def v_enum(body, name, choices, required=True, default=None):
    if not _present(body, name):
        if required:
            raise_err(ERR_INVALID_REQUEST, "missing required field: %s" % name)
        return default
    if body[name] not in choices:
        raise_err(ERR_INVALID_REQUEST, "field %s must be one of %s" % (name, sorted(choices)))
    return body[name]


def v_dt(body, name, required=True, default=None):
    if not _present(body, name):
        if required:
            raise_err(ERR_INVALID_REQUEST, "missing required field: %s" % name)
        return default
    return parse_dt(body[name])


# ---------------------------------------------------------------- pagination
def paginate(items):
    """Slice items per ?limit/?offset and return (page, pagination_meta)."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    try:
        limit = int(raw_limit) if raw_limit is not None else 10
    except (TypeError, ValueError):
        raise_err(ERR_INVALID_REQUEST, "limit must be an integer")
    try:
        offset = int(raw_offset) if raw_offset is not None else 0
    except (TypeError, ValueError):
        raise_err(ERR_INVALID_REQUEST, "offset must be an integer")
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    total = len(items)
    page = items[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(page) < total,
    }
    return page, meta
