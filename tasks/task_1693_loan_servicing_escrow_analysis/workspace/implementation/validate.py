"""Shared request-shape helpers (validation priority 5/6/18)."""

from flask import request

from errors import ApiError, ERR_INVALID_AMOUNT, ERR_INVALID_REQUEST, ERR_REF_NOT_FOUND
from util import parse_date


def body():
    return request.get_json(silent=True) or {}


def req_str(data, field):
    v = data.get(field)
    if not isinstance(v, str) or not v:
        raise ApiError(ERR_INVALID_REQUEST, 400, "%s is required and must be a string" % field)
    return v


def opt_str(data, field, default=None):
    v = data.get(field, default)
    if v is not None and not isinstance(v, str):
        raise ApiError(ERR_INVALID_REQUEST, 400, "%s must be a string" % field)
    return v


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def req_int(data, field, minimum=None):
    v = data.get(field)
    if not _is_int(v):
        raise ApiError(ERR_INVALID_REQUEST, 400, "%s is required and must be an integer" % field)
    if minimum is not None and v < minimum:
        raise ApiError(ERR_INVALID_REQUEST, 400, "%s must be >= %d" % (field, minimum))
    return v


def opt_int(data, field, default=None, minimum=None):
    if field not in data or data[field] is None:
        return default
    v = data[field]
    if not _is_int(v):
        raise ApiError(ERR_INVALID_REQUEST, 400, "%s must be an integer" % field)
    if minimum is not None and v < minimum:
        raise ApiError(ERR_INVALID_REQUEST, 400, "%s must be >= %d" % (field, minimum))
    return v


def req_enum(data, field, values):
    v = data.get(field)
    if v not in values:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "%s must be one of %s" % (field, ", ".join(values)))
    return v


def opt_enum(data, field, values, default=None):
    if field not in data or data[field] is None:
        return default
    return req_enum(data, field, values)


def req_date(data, field):
    v = data.get(field)
    d = parse_date(v)
    if d is None:
        raise ApiError(ERR_INVALID_REQUEST, 400, "%s must be an ISO YYYY-MM-DD date" % field)
    return v


def opt_bool(data, field, default=None):
    if field not in data or data[field] is None:
        return default
    v = data[field]
    if not isinstance(v, bool):
        raise ApiError(ERR_INVALID_REQUEST, 400, "%s must be a boolean" % field)
    return v


def fk_exists(table, value, field):
    """Priority 5: body foreign-key reference must exist."""
    if value is None:
        return None
    if not isinstance(value, str) or value not in table:
        raise ApiError(ERR_REF_NOT_FOUND, 422, "%s does not reference an existing resource" % field)
    return table[value]


def positive_amount(value, field="amount_cents"):
    """Priority 18: amounts must be positive integers."""
    if not _is_int(value) or value <= 0:
        raise ApiError(ERR_INVALID_AMOUNT, 422, "%s must be a positive integer" % field)
    return value
