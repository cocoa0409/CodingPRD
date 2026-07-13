"""Shared helpers for route modules."""
from flask import request

from errors import ApiError


def body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError("ERR_INVALID_REQUEST", "The request body must be a JSON object.")
    return data


def require_int(value, field, minimum=None, exclusive_min=None):
    if isinstance(value, bool) or not isinstance(value, int):
        raise ApiError("ERR_INVALID_REQUEST", "%s must be an integer." % field)
    if minimum is not None and value < minimum:
        raise ApiError("ERR_INVALID_REQUEST", "%s must be >= %s." % (field, minimum))
    if exclusive_min is not None and value <= exclusive_min:
        raise ApiError("ERR_INVALID_REQUEST", "%s must be > %s." % (field, exclusive_min))
    return value


def require_number(value, field, minimum=None, maximum=None):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ApiError("ERR_INVALID_REQUEST", "%s must be a number." % field)
    if minimum is not None and value < minimum:
        raise ApiError("ERR_INVALID_REQUEST", "%s must be >= %s." % (field, minimum))
    if maximum is not None and value > maximum:
        raise ApiError("ERR_INVALID_REQUEST", "%s must be <= %s." % (field, maximum))
    return float(value)


def require_string(value, field):
    if not isinstance(value, str) or not value.strip():
        raise ApiError("ERR_INVALID_REQUEST", "%s must be a non-empty string." % field)
    return value
