"""Request body parsing and field validation helpers.

All well-formedness failures map to ERR_INVALID_REQUEST (422), the priority-4
tier in PRD §2.8.
"""

from datetime import datetime, timezone

from errors import err


def get_body():
    from flask import request
    if request.data:
        try:
            data = request.get_json(force=True, silent=True)
        except Exception:
            data = None
    else:
        data = {}
    if data is None:
        raise err("ERR_INVALID_REQUEST", "Request body must be valid JSON")
    if not isinstance(data, dict):
        raise err("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    return data


def require(body, field):
    if field not in body or body[field] is None:
        raise err("ERR_INVALID_REQUEST", f"Missing required field: {field}")
    return body[field]


def as_str(value, field):
    if not isinstance(value, str):
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be a string")
    return value


def as_int(value, field):
    # bool is a subclass of int — reject it explicitly.
    if isinstance(value, bool) or not isinstance(value, int):
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be an integer")
    return value


def as_number(value, field):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be a number")
    return value


def as_bool(value, field):
    if not isinstance(value, bool):
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be a boolean")
    return value


def parse_dt(value, field):
    """Parse an ISO 8601 timestamp into an aware UTC datetime."""
    if not isinstance(value, str):
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be an ISO 8601 string")
    s = value.strip()
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise err("ERR_INVALID_REQUEST", f"Field {field} is not a valid ISO 8601 timestamp")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def require_int(body, field, *, minimum=None, gt=None):
    v = as_int(require(body, field), field)
    _range_check(v, field, minimum, gt)
    return v


def require_number(body, field, *, lo=None, hi=None, gt=None):
    v = as_number(require(body, field), field)
    if gt is not None and not (v > gt):
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be > {gt}")
    if lo is not None and v < lo:
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be >= {lo}")
    if hi is not None and v > hi:
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be <= {hi}")
    return v


def require_str(body, field):
    return as_str(require(body, field), field)


def _range_check(v, field, minimum, gt):
    if gt is not None and not (v > gt):
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be > {gt}")
    if minimum is not None and v < minimum:
        raise err("ERR_INVALID_REQUEST", f"Field {field} must be >= {minimum}")


def optional_int(body, field, default, *, minimum=None, gt=None):
    if field not in body or body[field] is None:
        return default
    v = as_int(body[field], field)
    _range_check(v, field, minimum, gt)
    return v


def optional_number(body, field, default, *, lo=None, hi=None, gt=None):
    if field not in body or body[field] is None:
        return default
    return require_number(body, field, lo=lo, hi=hi, gt=gt)


def optional_bool(body, field, default):
    if field not in body or body[field] is None:
        return default
    return as_bool(body[field], field)


def optional_str(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    return as_str(body[field], field)
