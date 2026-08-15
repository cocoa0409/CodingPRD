"""Time helpers and request-body validation helpers."""

from datetime import datetime, timezone

from flask import request

from errors import ApiError


# ---------------------------------------------------------------------------
# Time
# ---------------------------------------------------------------------------

def fmt(dt):
    """Canonical ISO 8601 UTC string with exactly three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "{:03d}Z".format(dt.microsecond // 1000)


def parse_datetime(value, field="datetime"):
    """Parse an ISO 8601 string into an aware UTC datetime, else ERR_VALIDATION."""
    if not isinstance(value, str) or not value.strip():
        raise ApiError("ERR_VALIDATION", 400, "{} must be an ISO 8601 datetime string".format(field))
    s = value.strip()
    if s.endswith(("Z", "z")):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise ApiError("ERR_VALIDATION", 400, "{} must be an ISO 8601 datetime string".format(field))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def floor_minutes(delta):
    """Whole-minute floor of a timedelta."""
    return int(delta.total_seconds() // 60)


# ---------------------------------------------------------------------------
# Body validation
# ---------------------------------------------------------------------------

def get_body():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ApiError("ERR_VALIDATION", 400, "request body must be a JSON object")
    return data


def req_string(data, field):
    v = data.get(field)
    if not isinstance(v, str):
        raise ApiError("ERR_VALIDATION", 400, "{} is required and must be a string".format(field))
    return v


def opt_string(data, field):
    v = data.get(field)
    if v is not None and not isinstance(v, str):
        raise ApiError("ERR_VALIDATION", 400, "{} must be a string".format(field))
    return v


def req_enum(data, field, allowed):
    v = data.get(field)
    if not isinstance(v, str) or v not in allowed:
        raise ApiError("ERR_VALIDATION", 400, "{} must be one of {}".format(field, sorted(allowed)))
    return v


def opt_enum(data, field, allowed, default):
    v = data.get(field)
    if v is None:
        return default
    if not isinstance(v, str) or v not in allowed:
        raise ApiError("ERR_VALIDATION", 400, "{} must be one of {}".format(field, sorted(allowed)))
    return v


def req_int(data, field, min_value=None, max_value=None):
    v = data.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError("ERR_VALIDATION", 400, "{} must be an integer".format(field))
    if min_value is not None and v < min_value:
        raise ApiError("ERR_VALIDATION", 400, "{} must be >= {}".format(field, min_value))
    if max_value is not None and v > max_value:
        raise ApiError("ERR_VALIDATION", 400, "{} must be <= {}".format(field, max_value))
    return v


def req_number(data, field, min_value=None):
    v = data.get(field)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ApiError("ERR_VALIDATION", 400, "{} must be a number".format(field))
    if min_value is not None and v < min_value:
        raise ApiError("ERR_VALIDATION", 400, "{} must be >= {}".format(field, min_value))
    return v


def opt_bool(data, field, default=False):
    v = data.get(field)
    if v is None:
        return default
    if not isinstance(v, bool):
        raise ApiError("ERR_VALIDATION", 400, "{} must be a boolean".format(field))
    return v


def req_datetime(data, field):
    v = data.get(field)
    if v is None:
        raise ApiError("ERR_VALIDATION", 400, "{} is required".format(field))
    return parse_datetime(v, field)


def opt_datetime(data, field):
    v = data.get(field)
    if v is None:
        return None
    return parse_datetime(v, field)
