"""Request body shape validation helpers (priority 0 — ERR_INVALID_REQUEST)."""

from errors import raise_err, ERR_INVALID_REQUEST
from flask import request


def get_json_body():
    """Parse JSON body; on failure raise ERR_INVALID_REQUEST.

    Empty bodies (common for action endpoints with no input) parse to {}.
    """
    raw = request.get_data()
    if raw is None or raw.strip() == b"":
        return {}
    data = request.get_json(silent=True)
    if data is None:
        raise_err(ERR_INVALID_REQUEST, "Request body must be valid JSON")
    if not isinstance(data, dict):
        raise_err(ERR_INVALID_REQUEST, "Request body must be a JSON object")
    return data


def require_fields(body, fields):
    """Ensure required fields are present (not None)."""
    if not isinstance(body, dict):
        raise_err(ERR_INVALID_REQUEST, "Request body must be a JSON object")
    for f in fields:
        if f not in body or body[f] is None:
            raise_err(ERR_INVALID_REQUEST, f"Missing required field: {f}")


def opt_str(body, name):
    v = body.get(name)
    if v is not None and not isinstance(v, str):
        raise_err(ERR_INVALID_REQUEST, f"Field {name} must be a string")
    return v


def req_str(body, name):
    v = body.get(name)
    if v is None:
        raise_err(ERR_INVALID_REQUEST, f"Missing required field: {name}")
    if not isinstance(v, str):
        raise_err(ERR_INVALID_REQUEST, f"Field {name} must be a string")
    return v


def req_int(body, name):
    v = body.get(name)
    if v is None:
        raise_err(ERR_INVALID_REQUEST, f"Missing required field: {name}")
    if isinstance(v, bool) or not isinstance(v, int):
        raise_err(ERR_INVALID_REQUEST, f"Field {name} must be an integer")
    return v


def opt_int(body, name):
    v = body.get(name)
    if v is not None and (isinstance(v, bool) or not isinstance(v, int)):
        raise_err(ERR_INVALID_REQUEST, f"Field {name} must be an integer")
    return v


def req_bool(body, name):
    v = body.get(name)
    if v is None:
        raise_err(ERR_INVALID_REQUEST, f"Missing required field: {name}")
    if not isinstance(v, bool):
        raise_err(ERR_INVALID_REQUEST, f"Field {name} must be a boolean")
    return v


def req_enum(body, name, allowed):
    v = body.get(name)
    if v is None:
        raise_err(ERR_INVALID_REQUEST, f"Missing required field: {name}")
    if not isinstance(v, str) or v not in allowed:
        raise_err(ERR_INVALID_REQUEST,
                  f"Field {name} must be one of {sorted(allowed)}")
    return v


def opt_enum(body, name, allowed):
    v = body.get(name)
    if v is not None and (not isinstance(v, str) or v not in allowed):
        raise_err(ERR_INVALID_REQUEST,
                  f"Field {name} must be one of {sorted(allowed)}")
    return v


def opt_str_list(body, name):
    v = body.get(name)
    if v is None:
        return None
    if not isinstance(v, list):
        raise_err(ERR_INVALID_REQUEST, f"Field {name} must be an array")
    for item in v:
        if not isinstance(item, str):
            raise_err(ERR_INVALID_REQUEST,
                      f"Field {name} must be an array of strings")
    return v
