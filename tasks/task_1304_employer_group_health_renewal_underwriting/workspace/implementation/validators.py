"""Request body shape validation helpers (ERR_INVALID_REQUEST, 400)."""
from flask import request

from errors import invalid_request


def body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise invalid_request("Request body must be a JSON object")
    return data


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def _is_num(v):
    return (isinstance(v, (int, float)) and not isinstance(v, bool))


def _missing(data, name):
    return name not in data or data[name] is None


def req_str(data, name):
    if _missing(data, name):
        raise invalid_request(f"Missing required field: {name}")
    v = data[name]
    if not isinstance(v, str):
        raise invalid_request(f"Field '{name}' must be a string")
    return v


def req_int(data, name):
    if _missing(data, name):
        raise invalid_request(f"Missing required field: {name}")
    v = data[name]
    if not _is_int(v):
        raise invalid_request(f"Field '{name}' must be an integer")
    return v


def req_num(data, name):
    if _missing(data, name):
        raise invalid_request(f"Missing required field: {name}")
    v = data[name]
    if not _is_num(v):
        raise invalid_request(f"Field '{name}' must be a number")
    return v


def req_dict(data, name):
    if _missing(data, name):
        raise invalid_request(f"Missing required field: {name}")
    v = data[name]
    if not isinstance(v, dict):
        raise invalid_request(f"Field '{name}' must be an object")
    return v


def req_enum(data, name, values):
    v = req_str(data, name)
    if v not in values:
        raise invalid_request(
            f"Field '{name}' must be one of: {', '.join(values)}"
        )
    return v


def opt_str(data, name):
    if _missing(data, name):
        return None
    v = data[name]
    if not isinstance(v, str):
        raise invalid_request(f"Field '{name}' must be a string")
    return v


def opt_int(data, name):
    if _missing(data, name):
        return None
    v = data[name]
    if not _is_int(v):
        raise invalid_request(f"Field '{name}' must be an integer")
    return v


def opt_num(data, name):
    if _missing(data, name):
        return None
    v = data[name]
    if not _is_num(v):
        raise invalid_request(f"Field '{name}' must be a number")
    return v


def opt_bool(data, name, default=False):
    if _missing(data, name):
        return default
    v = data[name]
    if not isinstance(v, bool):
        raise invalid_request(f"Field '{name}' must be a boolean")
    return v


def opt_list(data, name):
    if _missing(data, name):
        return None
    v = data[name]
    if not isinstance(v, list):
        raise invalid_request(f"Field '{name}' must be an array")
    return v
