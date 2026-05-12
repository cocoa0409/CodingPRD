"""Field-level validators raising APIError(ERR_INVALID_INPUT)."""
from clock import parse_iso
from errors import ERR_INVALID_INPUT, err


def require_field(data, name):
    if not isinstance(data, dict) or name not in data or data[name] is None:
        raise err(ERR_INVALID_INPUT, f"missing required field: {name}")
    return data[name]


def opt_field(data, name, default=None):
    if not isinstance(data, dict):
        return default
    if name not in data:
        return default
    return data[name]


def as_str(value, name, min_len=None, max_len=None):
    if not isinstance(value, str):
        raise err(ERR_INVALID_INPUT, f"{name} must be a string")
    if min_len is not None and len(value) < min_len:
        raise err(ERR_INVALID_INPUT, f"{name} too short")
    if max_len is not None and len(value) > max_len:
        raise err(ERR_INVALID_INPUT, f"{name} too long")
    return value


def as_int(value, name, mn=None, mx=None):
    # Accept bool as invalid integer (since bool is subclass of int).
    if isinstance(value, bool) or not isinstance(value, int):
        raise err(ERR_INVALID_INPUT, f"{name} must be an integer")
    if mn is not None and value < mn:
        raise err(ERR_INVALID_INPUT, f"{name} below minimum")
    if mx is not None and value > mx:
        raise err(ERR_INVALID_INPUT, f"{name} above maximum")
    return value


def as_number(value, name, mn=None, mx=None):
    if isinstance(value, bool):
        raise err(ERR_INVALID_INPUT, f"{name} must be a number")
    if not isinstance(value, (int, float)):
        raise err(ERR_INVALID_INPUT, f"{name} must be a number")
    v = float(value)
    if mn is not None and v < mn:
        raise err(ERR_INVALID_INPUT, f"{name} below minimum")
    if mx is not None and v > mx:
        raise err(ERR_INVALID_INPUT, f"{name} above maximum")
    return v


def as_lat(value, name="latitude"):
    return as_number(value, name, mn=-90.0, mx=90.0)


def as_lng(value, name="longitude"):
    return as_number(value, name, mn=-180.0, mx=180.0)


def as_enum(value, name, allowed):
    if value not in allowed:
        raise err(ERR_INVALID_INPUT, f"{name} must be one of {sorted(allowed)}")
    return value


def as_iso(value, name):
    if not isinstance(value, str):
        raise err(ERR_INVALID_INPUT, f"{name} must be an ISO 8601 string")
    try:
        return parse_iso(value)
    except Exception:
        raise err(ERR_INVALID_INPUT, f"{name} is not a valid ISO 8601 timestamp")


def as_bool(value, name):
    if not isinstance(value, bool):
        raise err(ERR_INVALID_INPUT, f"{name} must be a boolean")
    return value
