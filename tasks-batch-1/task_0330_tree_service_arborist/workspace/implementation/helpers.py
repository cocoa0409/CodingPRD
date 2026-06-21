"""Shared validation / parsing / rounding helpers."""
from decimal import Decimal, ROUND_HALF_UP

from flask import request

import errors
from errors import ApiError


def round_half_up(value):
    """Round a numeric value to a whole integer, half rounds up.

    Accepts int / float / Decimal. Money math composes Decimals to avoid
    float drift, then this collapses to integer cents.
    """
    if isinstance(value, Decimal):
        d = value
    else:
        # str() of a float is the shortest round-trippable repr; good enough,
        # but money paths pass Decimal already so this stays exact for them.
        d = Decimal(str(value))
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def get_json_body():
    """Return the request JSON body as a dict, or {} when absent/empty.

    A malformed (non-JSON) body raises ERR_INVALID_REQUEST.
    """
    if not request.data:
        return {}
    try:
        body = request.get_json(force=True, silent=False)
    except Exception:
        raise ApiError(errors.ERR_INVALID_REQUEST, 400, "Malformed request body.")
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise ApiError(errors.ERR_INVALID_REQUEST, 400, "Request body must be an object.")
    return body


def require_fields(body, *names):
    for name in names:
        if name not in body or body[name] is None:
            raise ApiError(errors.ERR_INVALID_REQUEST, 400,
                           f"Missing required field: {name}.")


def as_enum(body, field, allowed, required=True):
    if field not in body or body[field] is None:
        if required:
            raise ApiError(errors.ERR_INVALID_REQUEST, 400,
                           f"Missing required field: {field}.")
        return None
    value = body[field]
    if value not in allowed:
        raise ApiError(errors.ERR_INVALID_ENUM, 400,
                       f"Illegal value for {field}: {value!r}.")
    return value


def as_number(body, field, required=True, default=None):
    """Read a numeric field. Non-numeric / bool -> ERR_INVALID_REQUEST."""
    if field not in body or body[field] is None:
        if required:
            raise ApiError(errors.ERR_INVALID_REQUEST, 400,
                           f"Missing required field: {field}.")
        return default
    value = body[field]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ApiError(errors.ERR_INVALID_REQUEST, 400,
                       f"Field {field} must be a number.")
    return value


def as_int(body, field, required=True, default=None):
    if field not in body or body[field] is None:
        if required:
            raise ApiError(errors.ERR_INVALID_REQUEST, 400,
                           f"Missing required field: {field}.")
        return default
    value = body[field]
    if isinstance(value, bool):
        raise ApiError(errors.ERR_INVALID_REQUEST, 400,
                       f"Field {field} must be an integer.")
    if isinstance(value, float):
        if not value.is_integer():
            raise ApiError(errors.ERR_INVALID_REQUEST, 400,
                           f"Field {field} must be an integer.")
        return int(value)
    if not isinstance(value, int):
        raise ApiError(errors.ERR_INVALID_REQUEST, 400,
                       f"Field {field} must be an integer.")
    return value


def as_bool(body, field, default=False):
    if field not in body or body[field] is None:
        return default
    value = body[field]
    if not isinstance(value, bool):
        raise ApiError(errors.ERR_INVALID_REQUEST, 400,
                       f"Field {field} must be a boolean.")
    return value


def as_string(body, field, required=True, default=None):
    if field not in body or body[field] is None:
        if required:
            raise ApiError(errors.ERR_INVALID_REQUEST, 400,
                           f"Missing required field: {field}.")
        return default
    value = body[field]
    if not isinstance(value, str):
        raise ApiError(errors.ERR_INVALID_REQUEST, 400,
                       f"Field {field} must be a string.")
    return value


def parse_pagination():
    """Read limit/offset query params with PRD-defined defaults & bounds.

    limit default 10, min 1, max 100. offset default 0, min 0.
    Out-of-type values are coerced; clearly malformed -> ERR_INVALID_REQUEST.
    """
    limit = _parse_int_query("limit", 10)
    offset = _parse_int_query("offset", 0)
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    return limit, offset


def _parse_int_query(name, default):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        raise ApiError(errors.ERR_INVALID_REQUEST, 400,
                       f"Query parameter {name} must be an integer.")
