"""Field-level request-body validation helpers (ERR_INVALID_REQUEST, priority 15).

These enforce: required fields present, correct JSON types, enum membership,
numeric ranges. They are the lowest-priority backstop — auth/existence/state/
business checks run first in their respective routes.
"""
from errors import err


def require_object(body):
    if body is None or not isinstance(body, dict):
        raise err("ERR_INVALID_REQUEST", "request body must be a JSON object")
    return body


def req_str(body, key, allow_empty=False):
    if key not in body:
        raise err("ERR_INVALID_REQUEST", f"missing required field: {key}")
    val = body[key]
    if not isinstance(val, str):
        raise err("ERR_INVALID_REQUEST", f"{key} must be a string")
    if not allow_empty and val.strip() == "":
        raise err("ERR_INVALID_REQUEST", f"{key} must be non-empty")
    return val


def opt_str(body, key, default=None, allow_empty=False):
    if key not in body or body[key] is None:
        return default
    val = body[key]
    if not isinstance(val, str):
        raise err("ERR_INVALID_REQUEST", f"{key} must be a string")
    if not allow_empty and val.strip() == "":
        raise err("ERR_INVALID_REQUEST", f"{key} must be non-empty")
    return val


def _as_int(val, key):
    # Reject bools (a bool is an int subclass) and floats with a fractional part.
    if isinstance(val, bool):
        raise err("ERR_INVALID_REQUEST", f"{key} must be an integer")
    if isinstance(val, int):
        return val
    if isinstance(val, float) and val.is_integer():
        return int(val)
    raise err("ERR_INVALID_REQUEST", f"{key} must be an integer")


def req_int(body, key, minimum=None, maximum=None):
    if key not in body:
        raise err("ERR_INVALID_REQUEST", f"missing required field: {key}")
    val = _as_int(body[key], key)
    _check_range(val, key, minimum, maximum)
    return val


def opt_int(body, key, default=None, minimum=None, maximum=None):
    if key not in body or body[key] is None:
        return default
    val = _as_int(body[key], key)
    _check_range(val, key, minimum, maximum)
    return val


def _as_number(val, key):
    if isinstance(val, bool):
        raise err("ERR_INVALID_REQUEST", f"{key} must be a number")
    if isinstance(val, (int, float)):
        return val
    raise err("ERR_INVALID_REQUEST", f"{key} must be a number")


def req_number(body, key, minimum=None, maximum=None):
    if key not in body:
        raise err("ERR_INVALID_REQUEST", f"missing required field: {key}")
    val = _as_number(body[key], key)
    _check_range(val, key, minimum, maximum)
    return val


def opt_number(body, key, default=None, minimum=None, maximum=None):
    if key not in body or body[key] is None:
        return default
    val = _as_number(body[key], key)
    _check_range(val, key, minimum, maximum)
    return val


def req_bool(body, key):
    if key not in body:
        raise err("ERR_INVALID_REQUEST", f"missing required field: {key}")
    return _as_bool(body[key], key)


def opt_bool(body, key, default=None):
    if key not in body or body[key] is None:
        return default
    return _as_bool(body[key], key)


def _as_bool(val, key):
    if not isinstance(val, bool):
        raise err("ERR_INVALID_REQUEST", f"{key} must be a boolean")
    return val


def req_enum(body, key, members):
    val = req_str(body, key)
    if val not in members:
        raise err("ERR_INVALID_REQUEST", f"{key} must be one of {sorted(members)}")
    return val


def opt_enum(body, key, members, default=None):
    if key not in body or body[key] is None:
        return default
    val = body[key]
    if not isinstance(val, str) or val not in members:
        raise err("ERR_INVALID_REQUEST", f"{key} must be one of {sorted(members)}")
    return val


def _check_range(val, key, minimum, maximum):
    if minimum is not None and val < minimum:
        raise err("ERR_INVALID_REQUEST", f"{key} must be >= {minimum}")
    if maximum is not None and val > maximum:
        raise err("ERR_INVALID_REQUEST", f"{key} must be <= {maximum}")
