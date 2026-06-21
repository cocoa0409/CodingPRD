"""Field-level request validation helpers (ERR_INVALID_REQUEST family)."""
from datetime import datetime, timezone

from errors import ApiError


def require_body():
    from flask import request
    body = request.get_json(silent=True)
    if body is None or not isinstance(body, dict):
        raise ApiError("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return body


def req_str(body, field):
    if field not in body or body[field] is None:
        raise ApiError("ERR_INVALID_REQUEST", f"Missing required field: {field}")
    v = body[field]
    if not isinstance(v, str) or v == "":
        raise ApiError("ERR_INVALID_REQUEST", f"Field {field} must be a non-empty string.")
    return v


def opt_str(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if not isinstance(v, str):
        raise ApiError("ERR_INVALID_REQUEST", f"Field {field} must be a string.")
    return v


def req_int(body, field, minimum=None):
    if field not in body or body[field] is None:
        raise ApiError("ERR_INVALID_REQUEST", f"Missing required field: {field}")
    v = body[field]
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError("ERR_INVALID_REQUEST", f"Field {field} must be an integer.")
    if minimum is not None and v < minimum:
        raise ApiError("ERR_INVALID_REQUEST", f"Field {field} must be >= {minimum}.")
    return v


def opt_int(body, field, default=None, minimum=None):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError("ERR_INVALID_REQUEST", f"Field {field} must be an integer.")
    if minimum is not None and v < minimum:
        raise ApiError("ERR_INVALID_REQUEST", f"Field {field} must be >= {minimum}.")
    return v


def opt_bool(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if not isinstance(v, bool):
        raise ApiError("ERR_INVALID_REQUEST", f"Field {field} must be a boolean.")
    return v


def req_enum(body, field, allowed):
    v = req_str(body, field)
    if v not in allowed:
        raise ApiError("ERR_INVALID_REQUEST", f"Field {field} must be one of {sorted(allowed)}.")
    return v


def req_datetime(body, field):
    if field not in body or body[field] is None:
        raise ApiError("ERR_INVALID_REQUEST", f"Missing required field: {field}")
    return parse_dt(body[field], field)


def parse_dt(value, field="datetime"):
    if not isinstance(value, str):
        raise ApiError("ERR_INVALID_REQUEST", f"Field {field} must be an ISO 8601 string.")
    s = value.strip()
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise ApiError("ERR_INVALID_REQUEST", f"Field {field} must be a valid ISO 8601 datetime.")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
