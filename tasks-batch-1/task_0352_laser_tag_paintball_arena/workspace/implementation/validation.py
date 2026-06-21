"""Payload-shape validation (priority 4 -> ERR_VALIDATION) and pagination."""

from flask import request

from errors import err

PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0


def get_json_body():
    """Return the JSON body as a dict; tolerate empty/no body as {}."""
    if request.content_length in (None, 0):
        return {}
    data = request.get_json(silent=True)
    if data is None:
        # Body present but unparseable, or not an object.
        if request.data and request.data.strip():
            raise err("ERR_VALIDATION", "Request body is not valid JSON")
        return {}
    if not isinstance(data, dict):
        raise err("ERR_VALIDATION", "Request body must be a JSON object")
    return data


def require_string(body, name, allow_empty=False):
    v = body.get(name)
    if not isinstance(v, str):
        raise err("ERR_VALIDATION", f"Field '{name}' is required and must be a string")
    if not allow_empty and not v.strip():
        raise err("ERR_VALIDATION", f"Field '{name}' must not be empty")
    return v


def require_int(body, name, minimum=None, maximum=None):
    v = body.get(name)
    if isinstance(v, bool) or not isinstance(v, int):
        raise err("ERR_VALIDATION", f"Field '{name}' is required and must be an integer")
    if minimum is not None and v < minimum:
        raise err("ERR_VALIDATION", f"Field '{name}' must be >= {minimum}")
    if maximum is not None and v > maximum:
        raise err("ERR_VALIDATION", f"Field '{name}' must be <= {maximum}")
    return v


def optional_int(body, name, default=0, minimum=None, maximum=None):
    if name not in body or body.get(name) is None:
        return default
    return require_int(body, name, minimum=minimum, maximum=maximum)


def require_number(body, name, minimum=None, maximum=None, exclusive_max=None):
    v = body.get(name)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise err("ERR_VALIDATION", f"Field '{name}' is required and must be a number")
    if minimum is not None and v < minimum:
        raise err("ERR_VALIDATION", f"Field '{name}' must be >= {minimum}")
    if maximum is not None and v > maximum:
        raise err("ERR_VALIDATION", f"Field '{name}' must be <= {maximum}")
    if exclusive_max is not None and not (v < exclusive_max):
        raise err("ERR_VALIDATION", f"Field '{name}' must be < {exclusive_max}")
    return v


def optional_number(body, name, default, minimum=None, maximum=None, exclusive_max=None):
    if name not in body or body.get(name) is None:
        return default
    return require_number(body, name, minimum=minimum, maximum=maximum,
                          exclusive_max=exclusive_max)


def require_bool(body, name):
    v = body.get(name)
    if not isinstance(v, bool):
        raise err("ERR_VALIDATION", f"Field '{name}' must be a boolean")
    return v


def optional_bool(body, name, default):
    if name not in body or body.get(name) is None:
        return default
    return require_bool(body, name)


def require_enum(body, name, allowed):
    v = require_string(body, name)
    if v not in allowed:
        raise err("ERR_VALIDATION",
                  f"Field '{name}' must be one of {sorted(allowed)}")
    return v


def optional_enum(body, name, allowed, default):
    if name not in body or body.get(name) is None:
        return default
    return require_enum(body, name, allowed)


def parse_pagination():
    """Parse limit/offset query params with PRD §2.3 defaults/bounds."""
    limit = request.args.get("limit")
    offset = request.args.get("offset")
    if limit is None:
        limit_v = PAGINATION_DEFAULT_LIMIT
    else:
        try:
            limit_v = int(limit)
        except (TypeError, ValueError):
            raise err("ERR_VALIDATION", "limit must be an integer")
        if limit_v < PAGINATION_MIN_LIMIT:
            limit_v = PAGINATION_MIN_LIMIT
        if limit_v > PAGINATION_MAX_LIMIT:
            limit_v = PAGINATION_MAX_LIMIT
    if offset is None:
        offset_v = PAGINATION_DEFAULT_OFFSET
    else:
        try:
            offset_v = int(offset)
        except (TypeError, ValueError):
            raise err("ERR_VALIDATION", "offset must be an integer")
        if offset_v < 0:
            offset_v = 0
    return limit_v, offset_v
