"""Request-body well-formedness helpers (PRD §2.8 — ERR_VALIDATION)."""
from errors import err


def require_object(body):
    if not isinstance(body, dict):
        raise err("ERR_VALIDATION", "Request body must be a JSON object.")
    return body


def require_str(body, field, allow_empty=False):
    if field not in body:
        raise err("ERR_VALIDATION", f"Missing required field: {field}.")
    val = body[field]
    if not isinstance(val, str):
        raise err("ERR_VALIDATION", f"Field {field} must be a string.")
    if not allow_empty and val == "":
        raise err("ERR_VALIDATION", f"Field {field} must be non-empty.")
    return val


def require_enum(body, field, allowed):
    val = require_str(body, field)
    if val not in allowed:
        raise err("ERR_VALIDATION", f"Field {field} has an invalid value.")
    return val


def optional_enum(body, field, allowed, default):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if not isinstance(val, str) or val not in allowed:
        raise err("ERR_VALIDATION", f"Field {field} has an invalid value.")
    return val


def require_int(body, field, minimum=None, maximum=None):
    if field not in body:
        raise err("ERR_VALIDATION", f"Missing required field: {field}.")
    val = body[field]
    if isinstance(val, bool) or not isinstance(val, int):
        raise err("ERR_VALIDATION", f"Field {field} must be an integer.")
    if minimum is not None and val < minimum:
        raise err("ERR_VALIDATION", f"Field {field} is below the minimum.")
    if maximum is not None and val > maximum:
        raise err("ERR_VALIDATION", f"Field {field} is above the maximum.")
    return val


def optional_int(body, field, default, minimum=None, maximum=None):
    if field not in body or body[field] is None:
        return default
    return require_int(body, field, minimum=minimum, maximum=maximum)


def require_bool(body, field):
    if field not in body:
        raise err("ERR_VALIDATION", f"Missing required field: {field}.")
    val = body[field]
    if not isinstance(val, bool):
        raise err("ERR_VALIDATION", f"Field {field} must be a boolean.")
    return val


def optional_bool(body, field, default):
    if field not in body or body[field] is None:
        return default
    return require_bool(body, field)
