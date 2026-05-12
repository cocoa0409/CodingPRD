"""Shared validation helpers for body parsing."""
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation

from errors import err
from clock import parse_iso, is_first_of_month, to_utc_midnight


def require_body(req):
    if not req.is_json:
        raise err("ERR_VALIDATION", "Request body must be JSON")
    try:
        body = req.get_json(silent=False)
    except Exception:
        raise err("ERR_VALIDATION", "Invalid JSON body")
    if body is None:
        # Allow empty body for endpoints that take no input
        return {}
    if not isinstance(body, dict):
        raise err("ERR_VALIDATION", "Request body must be a JSON object")
    return body


def get_body(req):
    """Return JSON body as dict, allowing absent body to be {}."""
    if not req.data:
        return {}
    try:
        body = req.get_json(silent=True)
    except Exception:
        raise err("ERR_VALIDATION", "Invalid JSON body")
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise err("ERR_VALIDATION", "Request body must be a JSON object")
    return body


def require_field(body: dict, name: str):
    if name not in body or body[name] is None:
        raise err("ERR_VALIDATION", f"Missing required field: {name}")
    return body[name]


def require_str(body, name):
    v = require_field(body, name)
    if not isinstance(v, str) or not v.strip():
        raise err("ERR_VALIDATION", f"{name} must be a non-empty string")
    return v


def require_int(body, name, *, min_value=None, max_value=None):
    v = require_field(body, name)
    if isinstance(v, bool) or not isinstance(v, int):
        raise err("ERR_VALIDATION", f"{name} must be an integer")
    if min_value is not None and v < min_value:
        raise err("ERR_VALIDATION", f"{name} must be >= {min_value}")
    if max_value is not None and v > max_value:
        raise err("ERR_VALIDATION", f"{name} must be <= {max_value}")
    return v


def opt_int(body, name, *, min_value=None, max_value=None, default=None):
    if name not in body or body[name] is None:
        return default
    v = body[name]
    if isinstance(v, bool) or not isinstance(v, int):
        raise err("ERR_VALIDATION", f"{name} must be an integer")
    if min_value is not None and v < min_value:
        raise err("ERR_VALIDATION", f"{name} must be >= {min_value}")
    if max_value is not None and v > max_value:
        raise err("ERR_VALIDATION", f"{name} must be <= {max_value}")
    return v


def require_number(body, name, *, gt=None, ge=None):
    v = require_field(body, name)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise err("ERR_VALIDATION", f"{name} must be a number")
    f = float(v)
    if gt is not None and not (f > gt):
        raise err("ERR_VALIDATION", f"{name} must be > {gt}")
    if ge is not None and not (f >= ge):
        raise err("ERR_VALIDATION", f"{name} must be >= {ge}")
    return f


def opt_number(body, name, *, gt=None, ge=None, default=None):
    if name not in body or body[name] is None:
        return default
    v = body[name]
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise err("ERR_VALIDATION", f"{name} must be a number")
    f = float(v)
    if gt is not None and not (f > gt):
        raise err("ERR_VALIDATION", f"{name} must be > {gt}")
    if ge is not None and not (f >= ge):
        raise err("ERR_VALIDATION", f"{name} must be >= {ge}")
    return f


def require_enum(body, name, choices):
    v = require_field(body, name)
    if v not in choices:
        raise err("ERR_VALIDATION", f"{name} must be one of {sorted(choices)}")
    return v


def opt_enum(body, name, choices, default=None):
    if name not in body or body[name] is None:
        return default
    if body[name] not in choices:
        raise err("ERR_VALIDATION", f"{name} must be one of {sorted(choices)}")
    return body[name]


def require_iso(body, name):
    v = require_field(body, name)
    if not isinstance(v, str):
        raise err("ERR_VALIDATION", f"{name} must be an ISO 8601 string")
    try:
        dt = parse_iso(v)
    except ValueError:
        raise err("ERR_VALIDATION", f"{name} must be an ISO 8601 string")
    return dt


def opt_iso(body, name, default=None):
    if name not in body or body[name] is None:
        return default
    v = body[name]
    if not isinstance(v, str):
        raise err("ERR_VALIDATION", f"{name} must be an ISO 8601 string")
    try:
        return parse_iso(v)
    except ValueError:
        raise err("ERR_VALIDATION", f"{name} must be an ISO 8601 string")


def require_bool(body, name):
    v = require_field(body, name)
    if not isinstance(v, bool):
        raise err("ERR_VALIDATION", f"{name} must be a boolean")
    return v


def round_2dp(value) -> Decimal:
    """Quantize a number to 2dp using ROUND_HALF_UP."""
    try:
        d = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise err("ERR_VALIDATION", "Invalid number")
    return d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def num_2dp_match(a, b) -> bool:
    """Compare two numbers when both rounded to 2 decimal places."""
    return round_2dp(a) == round_2dp(b)
