"""Request-body well-formedness helpers (validation priority 5, ERR_INVALID_REQUEST).

Raises ERR_INVALID_REQUEST (422) for missing required fields, bad enums, or
out-of-range numerics.
"""
from flask import request

from errors import raise_err
import errors


def body():
    data = request.get_json(silent=True)
    if data is None or not isinstance(data, dict):
        raise_err(errors.ERR_INVALID_REQUEST, "JSON object body required")
    return data


def require(data, field):
    if field not in data or data[field] is None:
        raise_err(errors.ERR_INVALID_REQUEST, f"missing required field: {field}")
    return data[field]


def opt(data, field, default=None):
    if field not in data or data[field] is None:
        return default
    return data[field]


def as_str(value, field):
    if not isinstance(value, str) or value == "":
        raise_err(errors.ERR_INVALID_REQUEST, f"{field} must be a non-empty string")
    return value


def as_int(value, field, minimum=None, maximum=None):
    # bool is a subclass of int; reject it explicitly.
    if isinstance(value, bool) or not isinstance(value, int):
        raise_err(errors.ERR_INVALID_REQUEST, f"{field} must be an integer")
    if minimum is not None and value < minimum:
        raise_err(errors.ERR_INVALID_REQUEST, f"{field} below minimum")
    if maximum is not None and value > maximum:
        raise_err(errors.ERR_INVALID_REQUEST, f"{field} above maximum")
    return value


def as_number(value, field, minimum=None, maximum=None):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise_err(errors.ERR_INVALID_REQUEST, f"{field} must be a number")
    if minimum is not None and value < minimum:
        raise_err(errors.ERR_INVALID_REQUEST, f"{field} below minimum")
    if maximum is not None and value > maximum:
        raise_err(errors.ERR_INVALID_REQUEST, f"{field} above maximum")
    return value


def as_bool(value, field):
    if not isinstance(value, bool):
        raise_err(errors.ERR_INVALID_REQUEST, f"{field} must be a boolean")
    return value


def as_enum(value, field, allowed):
    if value not in allowed:
        raise_err(errors.ERR_INVALID_REQUEST, f"{field} must be one of {sorted(allowed)}")
    return value
