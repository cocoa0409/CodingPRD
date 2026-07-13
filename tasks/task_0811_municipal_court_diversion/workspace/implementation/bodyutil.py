"""Request-body parsing helpers. All failures raise ERR_VALIDATION (tier 11)."""

from decimal import Decimal, InvalidOperation
from flask import request

from errors import ApiError
from store import parse_iso_datetime


def get_body():
    data = request.get_json(silent=True)
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise ApiError("ERR_VALIDATION", "request body must be a JSON object")
    return data


def _present(body, name):
    return name in body and body[name] is not None


def req_str(body, name):
    v = body.get(name)
    if not isinstance(v, str) or v == "":
        raise ApiError("ERR_VALIDATION", f"'{name}' must be a non-empty string")
    return v


def req_enum(body, name, allowed):
    v = req_str(body, name)
    if v not in allowed:
        raise ApiError("ERR_VALIDATION", f"'{name}' must be one of {sorted(allowed)}")
    return v


def opt_enum(body, name, allowed, default):
    if not _present(body, name):
        return default
    return req_enum(body, name, allowed)


def _is_number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def req_decimal(body, name, minimum=None, exclusive_min=None):
    v = body.get(name)
    if not _is_number(v):
        raise ApiError("ERR_VALIDATION", f"'{name}' must be a number")
    try:
        d = Decimal(str(v))
    except (InvalidOperation, ValueError):
        raise ApiError("ERR_VALIDATION", f"'{name}' must be a number")
    if minimum is not None and d < minimum:
        raise ApiError("ERR_VALIDATION", f"'{name}' must be >= {minimum}")
    if exclusive_min is not None and d <= exclusive_min:
        raise ApiError("ERR_VALIDATION", f"'{name}' must be > {exclusive_min}")
    return d


def opt_decimal(body, name, default, minimum=None):
    if not _present(body, name):
        return default
    return req_decimal(body, name, minimum=minimum)


def req_int(body, name, minimum=None):
    v = body.get(name)
    if not isinstance(v, int) or isinstance(v, bool):
        raise ApiError("ERR_VALIDATION", f"'{name}' must be an integer")
    if minimum is not None and v < minimum:
        raise ApiError("ERR_VALIDATION", f"'{name}' must be >= {minimum}")
    return v


def opt_int(body, name, default, minimum=None):
    if not _present(body, name):
        return default
    return req_int(body, name, minimum=minimum)


def req_bool(body, name):
    v = body.get(name)
    if not isinstance(v, bool):
        raise ApiError("ERR_VALIDATION", f"'{name}' must be a boolean")
    return v


def opt_bool(body, name, default):
    if not _present(body, name):
        return default
    return req_bool(body, name)


def req_datetime(body, name):
    v = body.get(name)
    try:
        return parse_iso_datetime(v)
    except (ValueError, TypeError):
        raise ApiError("ERR_VALIDATION", f"'{name}' must be an ISO-8601 datetime")
