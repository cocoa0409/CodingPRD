"""Request body parsing and field-level type/range validation.

Any missing required field or a field violating its declared type/range constraint
raises ERR_VALIDATION (PRD §2.11). Field-shape validation is independent of the
priority-ordered business checks; it guards malformed input.
"""
from flask import request

import clock
from errors import err


def get_json_body():
    """Return the parsed JSON object body, or {} when absent. Non-object -> ERR_VALIDATION."""
    if request.method in ("GET", "DELETE"):
        return {}
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise err("ERR_VALIDATION", "Request body must be a JSON object.")
    return data


def require_str(body, field):
    if field not in body or body[field] is None:
        raise err("ERR_VALIDATION", f"Missing required field: {field}.")
    v = body[field]
    if not isinstance(v, str) or v.strip() == "":
        raise err("ERR_VALIDATION", f"Field {field} must be a non-empty string.")
    return v


def require_int(body, field, minimum=None, maximum=None):
    if field not in body or body[field] is None:
        raise err("ERR_VALIDATION", f"Missing required field: {field}.")
    v = body[field]
    if isinstance(v, bool) or not isinstance(v, int):
        raise err("ERR_VALIDATION", f"Field {field} must be an integer.")
    if minimum is not None and v < minimum:
        raise err("ERR_VALIDATION", f"Field {field} must be >= {minimum}.")
    if maximum is not None and v > maximum:
        raise err("ERR_VALIDATION", f"Field {field} must be <= {maximum}.")
    return v


def optional_int(body, field, default, minimum=None, maximum=None):
    if field not in body or body[field] is None:
        return default
    return require_int(body, field, minimum=minimum, maximum=maximum)


def require_bool(body, field, default=None):
    if field not in body or body[field] is None:
        if default is not None:
            return default
        raise err("ERR_VALIDATION", f"Missing required field: {field}.")
    v = body[field]
    if not isinstance(v, bool):
        raise err("ERR_VALIDATION", f"Field {field} must be a boolean.")
    return v


def optional_bool(body, field, default=False):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if not isinstance(v, bool):
        raise err("ERR_VALIDATION", f"Field {field} must be a boolean.")
    return v


def require_enum(body, field, allowed, default=None):
    if field not in body or body[field] is None:
        if default is not None:
            return default
        raise err("ERR_VALIDATION", f"Missing required field: {field}.")
    v = body[field]
    if v not in allowed:
        raise err("ERR_VALIDATION", f"Field {field} must be one of {sorted(allowed)}.")
    return v


def require_datetime(body, field):
    if field not in body or body[field] is None:
        raise err("ERR_VALIDATION", f"Missing required field: {field}.")
    try:
        return clock.parse_iso8601(body[field])
    except (ValueError, TypeError):
        raise err("ERR_VALIDATION", f"Field {field} must be an ISO 8601 datetime.")


def require_str_list(body, field):
    if field not in body or body[field] is None:
        raise err("ERR_VALIDATION", f"Missing required field: {field}.")
    v = body[field]
    if not isinstance(v, list) or len(v) == 0:
        raise err("ERR_VALIDATION", f"Field {field} must be a non-empty array.")
    for item in v:
        if not isinstance(item, str) or item.strip() == "":
            raise err("ERR_VALIDATION", f"Field {field} entries must be non-empty strings.")
    return v
