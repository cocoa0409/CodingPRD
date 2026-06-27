"""Body well-formedness (priority 5: ERR_INVALID_REQUEST) and semantic field
bounds (priority 6: ERR_VALIDATION) per PRD §2.9.

Ordering matters: ERR_INVALID_REQUEST (missing/typed/enum) is checked before
ERR_VALIDATION (numeric bounds) on an otherwise well-formed body.
"""
from errors import err


def require_present(body, field):
    if field not in body or body[field] is None:
        raise err("ERR_INVALID_REQUEST", "Missing required field: %s" % field)
    return body[field]


def require_str(body, field):
    val = require_present(body, field)
    if not isinstance(val, str) or val == "":
        raise err("ERR_INVALID_REQUEST", "Field %s must be a non-empty string" % field)
    return val


def require_int(body, field):
    val = require_present(body, field)
    # bool is a subclass of int; reject it explicitly.
    if isinstance(val, bool) or not isinstance(val, int):
        raise err("ERR_INVALID_REQUEST", "Field %s must be an integer" % field)
    return val


def optional_int(body, field, default):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if isinstance(val, bool) or not isinstance(val, int):
        raise err("ERR_INVALID_REQUEST", "Field %s must be an integer" % field)
    return val


def require_enum(body, field, choices):
    val = require_present(body, field)
    if not isinstance(val, str) or val not in choices:
        raise err("ERR_INVALID_REQUEST", "Field %s must be one of %s" % (field, sorted(choices)))
    return val


def optional_enum(body, field, choices, default):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if not isinstance(val, str) or val not in choices:
        raise err("ERR_INVALID_REQUEST", "Field %s must be one of %s" % (field, sorted(choices)))
    return val


def optional_bool(body, field, default):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if not isinstance(val, bool):
        raise err("ERR_INVALID_REQUEST", "Field %s must be a boolean" % field)
    return val


# ---- semantic bounds (priority 6: ERR_VALIDATION) -------------------------
def bound_positive(value, field):
    if value <= 0:
        raise err("ERR_VALIDATION", "Field %s must be > 0" % field)
    return value


def bound_min(value, minimum, field):
    if value < minimum:
        raise err("ERR_VALIDATION", "Field %s must be >= %d" % (field, minimum))
    return value
