"""Request-body shape/type validation helpers.

All shape failures raise ERR_INVALID_REQUEST (HTTP 400) per PRD section 2.1:
"a missing required key, a string where an integer is expected".
"""

from __future__ import annotations

from datetime import datetime, timezone

from flask import request

from errors import ApiError, ERR_INVALID_REQUEST


def invalid(msg: str = "Invalid request body") -> None:
    raise ApiError(ERR_INVALID_REQUEST, 400, msg)


def json_body(required: bool = True) -> dict:
    data = request.get_json(silent=True)
    if data is None:
        if required:
            invalid("Request body must be a JSON object")
        return {}
    if not isinstance(data, dict):
        invalid("Request body must be a JSON object")
    return data


def _is_int(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def req_str(body: dict, key: str) -> str:
    v = body.get(key)
    if not isinstance(v, str) or v == "":
        invalid(f"{key} is required and must be a non-empty string")
    return v


def opt_str(body: dict, key: str, default=None):
    if key not in body or body[key] is None:
        return default
    v = body[key]
    if not isinstance(v, str):
        invalid(f"{key} must be a string")
    return v


def req_int(body: dict, key: str, min_value=None) -> int:
    v = body.get(key)
    if not _is_int(v):
        invalid(f"{key} is required and must be an integer")
    if min_value is not None and v < min_value:
        invalid(f"{key} must be >= {min_value}")
    return v


def opt_int(body: dict, key: str, default=None, min_value=None):
    if key not in body or body[key] is None:
        return default
    v = body[key]
    if not _is_int(v):
        invalid(f"{key} must be an integer")
    if min_value is not None and v < min_value:
        invalid(f"{key} must be >= {min_value}")
    return v


def opt_bool(body: dict, key: str, default=False) -> bool:
    if key not in body or body[key] is None:
        return default
    v = body[key]
    if not isinstance(v, bool):
        invalid(f"{key} must be a boolean")
    return v


def req_enum(body: dict, key: str, allowed) -> str:
    v = body.get(key)
    if not isinstance(v, str) or v not in allowed:
        invalid(f"{key} must be one of {sorted(allowed)}")
    return v


def opt_number(body: dict, key: str, default=None):
    if key not in body or body[key] is None:
        return default
    v = body[key]
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        invalid(f"{key} must be a number")
    return v


def parse_iso(s):
    """Parse an ISO 8601 timestamp into an aware UTC datetime; None if bad."""
    if not isinstance(s, str):
        return None
    try:
        t = s.strip()
        if t.endswith("Z"):
            t = t[:-1] + "+00:00"
        dt = datetime.fromisoformat(t)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None
