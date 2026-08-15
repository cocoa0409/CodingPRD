"""Shared helpers: time handling, ids, pagination, validation."""

import math
import uuid
from datetime import datetime, timedelta, timezone

import errors

DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0


def new_id():
    return str(uuid.uuid4())


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def parse_dt(value):
    """Parse an ISO8601 datetime string to an aware datetime, or None on failure."""
    if not isinstance(value, str):
        return None
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def format_dt(dt):
    """Format an aware datetime to ISO8601 UTC with second precision and Z suffix."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def clock_dt():
    """Current logical clock as a datetime."""
    import db
    dt = parse_dt(db.logical_clock)
    return dt


def parse_pagination(args):
    """Parse limit/offset query params with defaults and range validation."""
    limit_raw = args.get("limit")
    offset_raw = args.get("offset")
    limit = DEFAULT_LIMIT
    offset = DEFAULT_OFFSET
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise errors.validation("limit must be an integer")
        if limit < MIN_LIMIT or limit > MAX_LIMIT:
            raise errors.validation("limit must be between 1 and 100")
    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise errors.validation("offset must be an integer")
        if offset < 0:
            raise errors.validation("offset must be >= 0")
    return limit, offset


def get_body():
    """Return the JSON request body as a dict ({} when absent)."""
    from flask import request
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise errors.validation("request body must be a JSON object")
    return data


def require_fields(body, fields):
    for f in fields:
        if f not in body or body[f] is None:
            raise errors.validation(f"missing required field: {f}")


def require_string(body, field):
    v = body.get(field)
    if not isinstance(v, str) or v == "":
        raise errors.validation(f"field {field} must be a non-empty string")
    return v


def optional_string(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if not isinstance(v, str):
        raise errors.validation(f"field {field} must be a string")
    return v


def require_enum(body, field, allowed):
    v = body.get(field)
    if v not in allowed:
        raise errors.validation(f"field {field} must be one of {sorted(allowed)}")
    return v


def optional_enum(body, field, allowed, default=None):
    if field not in body or body[field] is None:
        return default
    return require_enum(body, field, allowed)


def require_int(body, field, min_value=None, max_value=None):
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise errors.validation(f"field {field} must be an integer")
    if min_value is not None and v < min_value:
        raise errors.validation(f"field {field} must be >= {min_value}")
    if max_value is not None and v > max_value:
        raise errors.validation(f"field {field} must be <= {max_value}")
    return v


def optional_int(body, field, default=None, min_value=None, max_value=None):
    if field not in body or body[field] is None:
        return default
    return require_int(body, field, min_value=min_value, max_value=max_value)


def optional_bool(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if not isinstance(v, bool):
        raise errors.validation(f"field {field} must be a boolean")
    return v


def require_datetime(body, field):
    v = body.get(field)
    if not isinstance(v, str):
        raise errors.validation(f"field {field} must be an ISO8601 datetime string")
    dt = parse_dt(v)
    if dt is None:
        raise errors.validation(f"field {field} must be a valid ISO8601 datetime")
    return v


def require_string_list(body, field, allow_empty=False):
    v = body.get(field)
    if not isinstance(v, list):
        raise errors.validation(f"field {field} must be an array")
    if not allow_empty and len(v) == 0:
        raise errors.validation(f"field {field} must be non-empty")
    for item in v:
        if not isinstance(item, str) or item == "":
            raise errors.validation(f"field {field} must contain non-empty strings")
    return v


def parse_day_windows(body):
    """Validate the day_windows array. Returns the raw list (strings kept verbatim)."""
    v = body.get("day_windows")
    if not isinstance(v, list) or len(v) == 0:
        raise errors.validation("day_windows must be a non-empty array")
    out = []
    for entry in v:
        if not isinstance(entry, dict):
            raise errors.validation("day_windows entries must be objects")
        date = entry.get("date")
        start_at = entry.get("start_at")
        end_at = entry.get("end_at")
        if not isinstance(date, str) or not date:
            raise errors.validation("day_windows entry requires a date string")
        if not isinstance(start_at, str) or not isinstance(end_at, str):
            raise errors.validation("day_windows entry requires start_at and end_at strings")
        out.append({"date": date, "start_at": start_at, "end_at": end_at})
    return out


def minutes_between(a, b):
    """Whole minutes from datetime a to datetime b (b - a)."""
    return (b - a).total_seconds() / 60.0


def ceil_div_minutes(minutes, unit):
    if minutes <= 0:
        return 0
    return int(math.ceil(minutes / unit))
