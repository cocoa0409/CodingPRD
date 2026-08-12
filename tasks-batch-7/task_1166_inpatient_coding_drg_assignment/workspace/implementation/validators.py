"""Request body parsing and field validators (tier-7 ERR_INVALID_REQUEST helpers)."""
import re
from datetime import datetime, timezone

from flask import request

from errors import ApiError, ERR_INVALID_REQUEST

_INT_RE = re.compile(r"^-?\d+$")


def body():
    b = request.get_json(silent=True)
    if b is None:
        return {}
    if not isinstance(b, dict):
        raise ApiError(400, ERR_INVALID_REQUEST, "Request body must be a JSON object")
    return b


def has(b, field):
    return field in b and b[field] is not None


def req_str(b, field):
    v = b.get(field)
    if not isinstance(v, str) or v == "":
        raise ApiError(400, ERR_INVALID_REQUEST, f"{field} is required and must be a string")
    return v


def opt_str(b, field):
    v = b.get(field)
    if v is None:
        return None
    if not isinstance(v, str) or v == "":
        raise ApiError(400, ERR_INVALID_REQUEST, f"{field} must be a string")
    return v


def req_int(b, field):
    v = b.get(field)
    if isinstance(v, bool) or v is None:
        raise ApiError(400, ERR_INVALID_REQUEST, f"{field} is required and must be an integer")
    if isinstance(v, int):
        return v
    if isinstance(v, str) and _INT_RE.match(v.strip()):
        return int(v.strip())
    raise ApiError(400, ERR_INVALID_REQUEST, f"{field} must be an integer")


def opt_int(b, field):
    if not has(b, field):
        return None
    return req_int(b, field)


def req_bool(b, field):
    v = b.get(field)
    if not isinstance(v, bool):
        raise ApiError(400, ERR_INVALID_REQUEST, f"{field} is required and must be a boolean")
    return v


def opt_bool(b, field, default=None):
    v = b.get(field)
    if v is None:
        return default
    if not isinstance(v, bool):
        raise ApiError(400, ERR_INVALID_REQUEST, f"{field} must be a boolean")
    return v


def req_enum(b, field, members):
    v = b.get(field)
    if not isinstance(v, str) or v not in members:
        raise ApiError(400, ERR_INVALID_REQUEST,
                       f"{field} must be one of {', '.join(members)}")
    return v


def opt_enum(b, field, members, default=None):
    v = b.get(field)
    if v is None:
        return default
    if not isinstance(v, str) or v not in members:
        raise ApiError(400, ERR_INVALID_REQUEST,
                       f"{field} must be one of {', '.join(members)}")
    return v


def parse_dt(value, field):
    if not isinstance(value, str) or not value.strip():
        raise ApiError(400, ERR_INVALID_REQUEST,
                       f"{field} must be an ISO 8601 timestamp string")
    s = value.strip()
    if s.endswith("Z") or s.endswith("z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise ApiError(400, ERR_INVALID_REQUEST,
                       f"{field} must be a valid ISO 8601 timestamp")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def req_dt(b, field):
    if not has(b, field):
        raise ApiError(400, ERR_INVALID_REQUEST, f"{field} is required")
    return parse_dt(b.get(field), field)


def opt_dt(b, field):
    if not has(b, field):
        return None
    return parse_dt(b.get(field), field)
