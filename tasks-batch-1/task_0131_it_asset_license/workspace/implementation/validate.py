"""Request-body field validation helpers (PRD 2.8 priority 4: ERR_INVALID_REQUEST).

These enforce well-formedness: required fields present, enum values legal,
numeric fields constrained to >= 0 satisfy that constraint. They are applied
AFTER existence checks (priority 3) per the validation ladder.
"""
from errors import err


def require_body(body):
    if body is None or not isinstance(body, dict):
        raise err("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    return body


def req_str(body, field):
    v = body.get(field)
    if not isinstance(v, str) or v == "":
        raise err("ERR_INVALID_REQUEST", "Field %r must be a non-empty string" % field)
    return v


def opt_str(body, field, default=None):
    if field not in body or body.get(field) is None:
        return default
    v = body.get(field)
    if not isinstance(v, str) or v == "":
        raise err("ERR_INVALID_REQUEST", "Field %r must be a non-empty string" % field)
    return v


def req_enum(body, field, choices):
    v = body.get(field)
    if v not in choices:
        raise err("ERR_INVALID_REQUEST", "Field %r must be one of %s" % (field, sorted(choices)))
    return v


def opt_enum(body, field, choices, default=None):
    if field not in body or body.get(field) is None:
        return default
    return req_enum(body, field, choices)


def _as_int(value, field):
    # Reject bools (bool is an int subclass) and non-integers.
    if isinstance(value, bool) or not isinstance(value, int):
        raise err("ERR_INVALID_REQUEST", "Field %r must be an integer" % field)
    return value


def req_int(body, field, min_value=None):
    if field not in body or body.get(field) is None:
        raise err("ERR_INVALID_REQUEST", "Field %r is required" % field)
    v = _as_int(body.get(field), field)
    if min_value is not None and v < min_value:
        raise err("ERR_INVALID_REQUEST", "Field %r must be >= %s" % (field, min_value))
    return v


def opt_int(body, field, default=0, min_value=None):
    if field not in body or body.get(field) is None:
        return default
    v = _as_int(body.get(field), field)
    if min_value is not None and v < min_value:
        raise err("ERR_INVALID_REQUEST", "Field %r must be >= %s" % (field, min_value))
    return v


def req_number(body, field, min_value=None):
    if field not in body or body.get(field) is None:
        raise err("ERR_INVALID_REQUEST", "Field %r is required" % field)
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise err("ERR_INVALID_REQUEST", "Field %r must be a number" % field)
    if min_value is not None and v < min_value:
        raise err("ERR_INVALID_REQUEST", "Field %r must be >= %s" % (field, min_value))
    return float(v)


def opt_number(body, field, default, min_value=None):
    if field not in body or body.get(field) is None:
        return default
    return req_number(body, field, min_value)


def opt_bool(body, field, default):
    if field not in body or body.get(field) is None:
        return default
    v = body.get(field)
    if not isinstance(v, bool):
        raise err("ERR_INVALID_REQUEST", "Field %r must be a boolean" % field)
    return v
