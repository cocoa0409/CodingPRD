"""Request-shape validation helpers (PRD §2.8 step 5)."""

from datetime import date

from errors import err_invalid_request


def require_body(data):
    if data is None or not isinstance(data, dict):
        raise err_invalid_request("Request body must be a JSON object")
    return data


def check_unknown_fields(data, allowed):
    for k in data:
        if k not in allowed:
            raise err_invalid_request(f"Unknown field: {k}")


def req_field(data, name):
    if name not in data or data[name] is None:
        raise err_invalid_request(f"Missing required field: {name}")
    return data[name]


def req_str(data, name):
    v = req_field(data, name)
    if not isinstance(v, str) or not v:
        raise err_invalid_request(f"{name} must be a non-empty string")
    return v


def opt_str(data, name, default=None):
    if name not in data or data[name] is None:
        return default
    v = data[name]
    if not isinstance(v, str):
        raise err_invalid_request(f"{name} must be a string")
    return v


def req_int(data, name):
    v = req_field(data, name)
    if isinstance(v, bool) or not isinstance(v, int):
        raise err_invalid_request(f"{name} must be an integer")
    return v


def opt_int(data, name, default=None):
    if name not in data or data[name] is None:
        return default
    v = data[name]
    if isinstance(v, bool) or not isinstance(v, int):
        raise err_invalid_request(f"{name} must be an integer")
    return v


def req_enum(data, name, allowed):
    v = req_field(data, name)
    if v not in allowed:
        raise err_invalid_request(f"{name} must be one of {sorted(allowed)}")
    return v


def req_bool(data, name):
    v = req_field(data, name)
    if not isinstance(v, bool):
        raise err_invalid_request(f"{name} must be a boolean")
    return v


def opt_bool(data, name, default=False):
    if name not in data or data[name] is None:
        return default
    v = data[name]
    if not isinstance(v, bool):
        raise err_invalid_request(f"{name} must be a boolean")
    return v


def req_date(data, name):
    v = req_str(data, name)
    try:
        date.fromisoformat(v)
    except ValueError:
        raise err_invalid_request(f"{name} must be an ISO date YYYY-MM-DD")
    if len(v) != 10:
        raise err_invalid_request(f"{name} must be an ISO date YYYY-MM-DD")
    return v


def opt_date(data, name, default=None):
    if name not in data or data[name] is None:
        return default
    return req_date(data, name)
