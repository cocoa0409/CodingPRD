"""Shared helpers: datetime parsing/rendering, body extraction, field
validation, pagination."""
from datetime import datetime, timezone

from flask import request

import clock
from errors import ApiError, raise_err, ERR_VALIDATION


# ---------------------------------------------------------------- datetimes
def parse_datetime(value, field="datetime"):
    if not isinstance(value, str):
        raise_err(ERR_VALIDATION, f"{field} must be an ISO 8601 string")
    s = value.strip()
    if s.endswith(("Z", "z")):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise_err(ERR_VALIDATION, f"{field} is not a valid ISO 8601 datetime")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def render_dt(dt):
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def midnight_crossings(a, b):
    """Count of 00:00:00Z instants M with a < M <= b (a, b aware UTC)."""
    return (b.date() - a.date()).days


def floor_minutes(delta):
    """Timedelta -> whole minutes, exact to the second then floored."""
    return int(delta.total_seconds() // 60)


# ---------------------------------------------------------------- body
def body():
    raw = request.get_data(cache=True)
    if raw is None or len(raw.strip()) == 0:
        return {}
    data = request.get_json(silent=True)
    if data is None:
        raise_err(ERR_VALIDATION, "Request body is not valid JSON")
    if not isinstance(data, dict):
        raise_err(ERR_VALIDATION, "Request body must be a JSON object")
    return data


# ---------------------------------------------------------------- fields
def _present(b, name):
    return name in b and b[name] is not None


def req_field(b, name):
    if not _present(b, name):
        raise_err(ERR_VALIDATION, f"Missing required field: {name}")
    return b[name]


def req_str(b, name):
    v = req_field(b, name)
    if not isinstance(v, str):
        raise_err(ERR_VALIDATION, f"{name} must be a string")
    return v


def opt_str(b, name, default=None):
    if not _present(b, name):
        return default
    v = b[name]
    if not isinstance(v, str):
        raise_err(ERR_VALIDATION, f"{name} must be a string")
    return v


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def req_int(b, name, min_value=None):
    v = req_field(b, name)
    if not _is_int(v):
        raise_err(ERR_VALIDATION, f"{name} must be an integer")
    if min_value is not None and v < min_value:
        raise_err(ERR_VALIDATION, f"{name} must be >= {min_value}")
    return v


def opt_int(b, name, default=None, min_value=None):
    if not _present(b, name):
        return default
    v = b[name]
    if not _is_int(v):
        raise_err(ERR_VALIDATION, f"{name} must be an integer")
    if min_value is not None and v < min_value:
        raise_err(ERR_VALIDATION, f"{name} must be >= {min_value}")
    return v


def req_num(b, name):
    v = req_field(b, name)
    if not (isinstance(v, (int, float)) and not isinstance(v, bool)):
        raise_err(ERR_VALIDATION, f"{name} must be a number")
    return v


def opt_bool(b, name, default=False):
    if not _present(b, name):
        return default
    v = b[name]
    if not isinstance(v, bool):
        raise_err(ERR_VALIDATION, f"{name} must be a boolean")
    return v


def req_enum(b, name, allowed):
    v = req_field(b, name)
    if v not in allowed:
        raise_err(ERR_VALIDATION, f"{name} must be one of {sorted(allowed)}")
    return v


def req_dt(b, name):
    return parse_datetime(req_field(b, name), name)


def req_list(b, name):
    v = req_field(b, name)
    if not isinstance(v, list):
        raise_err(ERR_VALIDATION, f"{name} must be an array")
    return v


# ---------------------------------------------------------------- pagination
def paginate(items):
    limit_raw = request.args.get("limit", "10")
    offset_raw = request.args.get("offset", "0")
    try:
        limit = int(limit_raw)
    except (TypeError, ValueError):
        raise_err(ERR_VALIDATION, "limit must be an integer")
    try:
        offset = int(offset_raw)
    except (TypeError, ValueError):
        raise_err(ERR_VALIDATION, "offset must be an integer")
    if limit < 1 or limit > 100:
        raise_err(ERR_VALIDATION, "limit must be between 1 and 100")
    if offset < 0:
        raise_err(ERR_VALIDATION, "offset must be >= 0")
    total = len(items)
    page = items[offset:offset + limit]
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(page) < total,
    }
    return page, pagination


def touch(rec):
    """Version bump + updated_at refresh on every mutation."""
    rec["version"] += 1
    rec["updated_at"] = clock.now()
