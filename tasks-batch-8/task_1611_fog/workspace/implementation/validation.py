"""Request-body validation helpers (priority-2 ERR_INVALID_REQUEST checks)
plus datetime parsing/formatting at second precision."""
import json
from datetime import datetime, timezone

from flask import request

from errors import ApiError, ERR_INVALID_REQUEST


def _bad(msg):
    raise ApiError(ERR_INVALID_REQUEST, 400, msg)


def body_json():
    raw = request.get_data()
    if not raw or not raw.strip():
        return {}
    try:
        data = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        _bad("Request body must be valid JSON")
    if not isinstance(data, dict):
        _bad("Request body must be a JSON object")
    return data


def parse_dt(value, field="datetime"):
    """Parse an ISO 8601 datetime string, normalize to naive UTC truncated to
    second precision (all datetime comparisons operate at second precision)."""
    if not isinstance(value, str):
        _bad(f"Field '{field}' must be an ISO 8601 datetime string")
    s = value.strip()
    if s.endswith(("Z", "z")):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        _bad(f"Field '{field}' is not a valid ISO 8601 datetime")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc).replace(tzinfo=None, microsecond=0)
    return dt


def fmt_dt(dt):
    if dt is None:
        return None
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + ".000Z"


def v_str(body, name, required=True):
    if name not in body or body[name] is None:
        if required:
            _bad(f"Missing required field: {name}")
        return None
    val = body[name]
    if not isinstance(val, str):
        _bad(f"Field '{name}' must be a string")
    return val


def v_int(body, name, required=True, min_val=None):
    if name not in body or body[name] is None:
        if required:
            _bad(f"Missing required field: {name}")
        return None
    val = body[name]
    if isinstance(val, bool) or not isinstance(val, int):
        _bad(f"Field '{name}' must be an integer")
    if min_val is not None and val < min_val:
        _bad(f"Field '{name}' must be >= {min_val}")
    return val


def v_num(body, name, required=True, gt=None):
    """Numeric field (int or float). gt: exclusive lower bound."""
    if name not in body or body[name] is None:
        if required:
            _bad(f"Missing required field: {name}")
        return None
    val = body[name]
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        _bad(f"Field '{name}' must be a number")
    if gt is not None and not val > gt:
        _bad(f"Field '{name}' must be > {gt}")
    return val


def v_bool(body, name, required=True, default=None):
    if name not in body or body[name] is None:
        if required:
            _bad(f"Missing required field: {name}")
        return default
    val = body[name]
    if not isinstance(val, bool):
        _bad(f"Field '{name}' must be a boolean")
    return val


def v_enum(body, name, allowed, required=True):
    if name not in body or body[name] is None:
        if required:
            _bad(f"Missing required field: {name}")
        return None
    val = body[name]
    if not isinstance(val, str) or val not in allowed:
        _bad(f"Field '{name}' must be one of {sorted(allowed)}")
    return val


def v_dt(body, name, required=True):
    if name not in body or body[name] is None:
        if required:
            _bad(f"Missing required field: {name}")
        return None
    return parse_dt(body[name], field=name)
