"""Datetime and request-field helpers. Timestamps serialize as ISO 8601 UTC
with three fractional digits (e.g. 2026-08-01T00:00:00.000Z)."""
from datetime import datetime, timezone

from errors import validation


def fmt_dt(dt):
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_dt(value, field):
    if not isinstance(value, str):
        raise validation(f"Field '{field}' must be an ISO 8601 datetime string")
    text = value.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        raise validation(f"Field '{field}' is not a valid ISO 8601 datetime")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def req_str(data, field):
    v = data.get(field)
    if not isinstance(v, str) or v == "":
        raise validation(f"Field '{field}' is required and must be a non-empty string")
    return v


def opt_str(data, field, default=None):
    v = data.get(field, default)
    if v is not None and not isinstance(v, str):
        raise validation(f"Field '{field}' must be a string")
    return v


def req_enum(data, field, allowed):
    v = data.get(field)
    if v not in allowed:
        raise validation(f"Field '{field}' must be one of {sorted(allowed)}")
    return v


def opt_enum(data, field, allowed, default=None):
    if field not in data or data.get(field) is None:
        return default
    return req_enum(data, field, allowed)


def req_int(data, field, minimum=None):
    v = data.get(field)
    if not is_int(v):
        raise validation(f"Field '{field}' is required and must be an integer")
    if minimum is not None and v < minimum:
        raise validation(f"Field '{field}' must be >= {minimum}")
    return v


def opt_int(data, field, default=None, minimum=None):
    if field not in data or data.get(field) is None:
        return default
    return req_int(data, field, minimum=minimum)


def req_bool(data, field):
    v = data.get(field)
    if not isinstance(v, bool):
        raise validation(f"Field '{field}' is required and must be a boolean")
    return v


def opt_bool(data, field, default=False):
    if field not in data or data.get(field) is None:
        return default
    return req_bool(data, field)


def req_dt(data, field):
    if field not in data or data.get(field) is None:
        raise validation(f"Field '{field}' is required")
    return parse_dt(data.get(field), field)


def ceil_div(a, b):
    return -(-a // b)
