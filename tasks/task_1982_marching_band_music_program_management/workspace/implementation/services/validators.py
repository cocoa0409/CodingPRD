"""Common validation helpers."""
from flask import request
from errors import raise_err, ERR_INVALID_REQUEST


def body():
    """Return parsed JSON body or raise ERR_INVALID_REQUEST."""
    try:
        data = request.get_json(force=True, silent=False)
    except Exception:
        raise_err(ERR_INVALID_REQUEST, "request body must be JSON")
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise_err(ERR_INVALID_REQUEST, "request body must be a JSON object")
    return data


def require(data, *fields):
    """Require presence of fields."""
    for f in fields:
        if f not in data or data[f] is None:
            raise_err(ERR_INVALID_REQUEST, f"missing required field: {f}")


def check_unknown(data, allowed):
    """Reject unknown fields."""
    for k in data.keys():
        if k not in allowed:
            raise_err(ERR_INVALID_REQUEST, f"unknown field: {k}")


def to_int(v, name):
    if isinstance(v, bool):
        raise_err(ERR_INVALID_REQUEST, f"{name} must be integer")
    if isinstance(v, int):
        return v
    if isinstance(v, float) and v.is_integer():
        return int(v)
    raise_err(ERR_INVALID_REQUEST, f"{name} must be integer")


def to_str(v, name):
    if not isinstance(v, str):
        raise_err(ERR_INVALID_REQUEST, f"{name} must be a string")
    return v


def to_bool(v, name):
    if not isinstance(v, bool):
        raise_err(ERR_INVALID_REQUEST, f"{name} must be a boolean")
    return v


def to_enum(v, name, allowed):
    if v not in allowed:
        raise_err(ERR_INVALID_REQUEST, f"{name} must be one of {sorted(allowed)}")
    return v
