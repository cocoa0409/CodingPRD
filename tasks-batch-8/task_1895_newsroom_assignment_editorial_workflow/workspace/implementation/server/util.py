"""Timestamp, body, and pagination helpers."""

from datetime import datetime, timezone

from flask import request

from .errors import bad_request


def fmt_dt(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_dt(value):
    if not isinstance(value, str) or not value.strip():
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
    return dt.astimezone(timezone.utc)


def body():
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def req_present(b, name):
    if name not in b or b[name] is None:
        bad_request(f"Missing required field: {name}")
    return b[name]


def req_int(b, name, minimum=None):
    v = req_present(b, name)
    if not is_int(v):
        bad_request(f"Field {name} must be an integer")
    if minimum is not None and v < minimum:
        bad_request(f"Field {name} must be >= {minimum}")
    return v


def opt_int(b, name, default=None, minimum=None):
    if name not in b or b[name] is None:
        return default
    if not is_int(b[name]):
        bad_request(f"Field {name} must be an integer")
    if minimum is not None and b[name] < minimum:
        bad_request(f"Field {name} must be >= {minimum}")
    return b[name]


def req_str(b, name):
    v = req_present(b, name)
    if not isinstance(v, str):
        bad_request(f"Field {name} must be a string")
    return v


def opt_str(b, name, default=None):
    if name not in b or b[name] is None:
        return default
    if not isinstance(b[name], str):
        bad_request(f"Field {name} must be a string")
    return b[name]


def req_enum(b, name, allowed):
    v = req_str(b, name)
    if v not in allowed:
        bad_request(f"Field {name} must be one of {sorted(allowed)}")
    return v


def opt_enum(b, name, allowed, default=None):
    if name not in b or b[name] is None:
        return default
    return req_enum(b, name, allowed)


def req_dt(b, name):
    v = req_present(b, name)
    dt = parse_dt(v)
    if dt is None:
        bad_request(f"Field {name} must be an ISO8601 timestamp")
    return dt


def opt_dt(b, name, default=None):
    if name not in b or b[name] is None:
        return default
    dt = parse_dt(b[name])
    if dt is None:
        bad_request(f"Field {name} must be an ISO8601 timestamp")
    return dt


def pagination_params():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    try:
        limit = int(raw_limit) if raw_limit is not None else 10
    except (ValueError, TypeError):
        limit = 10
    try:
        offset = int(raw_offset) if raw_offset is not None else 0
    except (ValueError, TypeError):
        offset = 0
    limit = max(1, min(100, limit))
    offset = max(0, offset)
    return limit, offset


def sort_created(items):
    return sorted(items, key=lambda e: (e["created_at"], e["_seq"]))


def paged(items, limit, offset):
    total = len(items)
    return items[offset:offset + limit], total
