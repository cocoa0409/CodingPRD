"""Request body parsing/validation helpers.

These raise ERR_INVALID_REQUEST (422) for malformed bodies. Existence checks
live in the route/service layer and raise ERR_NOT_FOUND (404) — existence is
priority 3, body validation is priority 4, so existence is resolved first.
"""
from flask import request
from errors import err, ERR_INVALID_REQUEST


def get_json_body():
    """Return the parsed JSON body as a dict, or {} when absent/empty.

    Malformed JSON -> ERR_INVALID_REQUEST.
    """
    if request.method in ("GET", "HEAD"):
        return {}
    raw = request.get_data(cache=True) or b""
    if not raw.strip():
        return {}
    try:
        data = request.get_json(force=True, silent=False)
    except Exception:
        raise err(ERR_INVALID_REQUEST, "Malformed JSON body")
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise err(ERR_INVALID_REQUEST, "Request body must be a JSON object")
    return data


def require_str(body, name):
    val = body.get(name)
    if not isinstance(val, str) or val.strip() == "":
        raise err(ERR_INVALID_REQUEST, f"Field '{name}' is required and must be a non-empty string")
    return val


def optional_str(body, name, default=None):
    if name not in body or body.get(name) is None:
        return default
    val = body.get(name)
    if not isinstance(val, str):
        raise err(ERR_INVALID_REQUEST, f"Field '{name}' must be a string")
    return val


def require_enum(body, name, allowed):
    val = require_str(body, name)
    if val not in allowed:
        raise err(ERR_INVALID_REQUEST, f"Field '{name}' must be one of {sorted(allowed)}")
    return val


def optional_enum(body, name, allowed, default=None):
    if name not in body or body.get(name) is None:
        return default
    val = body.get(name)
    if val not in allowed:
        raise err(ERR_INVALID_REQUEST, f"Field '{name}' must be one of {sorted(allowed)}")
    return val


def _as_int(val, name):
    # Bool is a subclass of int; reject it explicitly.
    if isinstance(val, bool) or not isinstance(val, int):
        raise err(ERR_INVALID_REQUEST, f"Field '{name}' must be an integer")
    return val


def require_int(body, name, minimum=None):
    if name not in body or body.get(name) is None:
        raise err(ERR_INVALID_REQUEST, f"Field '{name}' is required")
    val = _as_int(body.get(name), name)
    if minimum is not None and val < minimum:
        raise err(ERR_INVALID_REQUEST, f"Field '{name}' must be >= {minimum}")
    return val


def optional_int(body, name, default=0, minimum=None):
    if name not in body or body.get(name) is None:
        return default
    val = _as_int(body.get(name), name)
    if minimum is not None and val < minimum:
        raise err(ERR_INVALID_REQUEST, f"Field '{name}' must be >= {minimum}")
    return val


def optional_number(body, name, default=0, minimum=None, maximum=None):
    if name not in body or body.get(name) is None:
        return default
    val = body.get(name)
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise err(ERR_INVALID_REQUEST, f"Field '{name}' must be a number")
    if minimum is not None and val < minimum:
        raise err(ERR_INVALID_REQUEST, f"Field '{name}' must be >= {minimum}")
    if maximum is not None and val > maximum:
        raise err(ERR_INVALID_REQUEST, f"Field '{name}' must be <= {maximum}")
    return val
