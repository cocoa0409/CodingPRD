"""Request-body validation helpers (priority 20: ERR_INVALID_REQUEST).

Note on ordering (PRD §2.8): auth -> role -> existence -> state -> OCC ->
temporal -> safety -> referential -> constraints -> fiscal -> request shape.
In practice request-shape failures for *required* fields are raised as the
body is consumed, which the PRD's own ordering example sanctions (shape
validation is last only when pitted against other rule categories on the
same request).
"""

from decimal import Decimal, InvalidOperation

from errors import invalid_request


def body():
    """Return the JSON request body as a dict, or raise ERR_INVALID_REQUEST."""
    from flask import request
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise invalid_request("request body must be a JSON object")
    return data


def require_string(data, field):
    v = data.get(field)
    if v is None:
        raise invalid_request(f"missing required field: {field}")
    if not isinstance(v, str) or not v.strip():
        raise invalid_request(f"field {field} must be a non-empty string")
    return v


def optional_string(data, field, default=None):
    v = data.get(field)
    if v is None:
        return default
    if not isinstance(v, str):
        raise invalid_request(f"field {field} must be a string")
    return v


def require_int(data, field):
    v = data.get(field)
    if v is None:
        raise invalid_request(f"missing required field: {field}")
    if isinstance(v, bool) or not isinstance(v, int):
        raise invalid_request(f"field {field} must be an integer")
    return v


def require_non_negative_int(data, field):
    v = require_int(data, field)
    if v < 0:
        raise invalid_request(f"field {field} must be a non-negative integer")
    return v


def require_decimal(data, field):
    """Accept an int/float/str numeric; returns Decimal. Rejects bool/null."""
    v = data.get(field)
    if v is None:
        raise invalid_request(f"missing required field: {field}")
    if isinstance(v, bool):
        raise invalid_request(f"field {field} must be a number")
    if isinstance(v, (int, float, str)):
        try:
            d = Decimal(str(v))
        except InvalidOperation:
            raise invalid_request(f"field {field} must be a number")
        if not d.is_finite():
            raise invalid_request(f"field {field} must be a finite number")
        return d
    raise invalid_request(f"field {field} must be a number")


def optional_decimal(data, field, default=None):
    v = data.get(field)
    if v is None:
        return default
    return require_decimal(data, field)


def require_bool(data, field):
    v = data.get(field)
    if v is None:
        raise invalid_request(f"missing required field: {field}")
    if not isinstance(v, bool):
        raise invalid_request(f"field {field} must be a boolean")
    return v


def optional_bool(data, field, default=False):
    v = data.get(field)
    if v is None:
        return default
    if not isinstance(v, bool):
        raise invalid_request(f"field {field} must be a boolean")
    return v


def require_enum(data, field, allowed):
    v = data.get(field)
    if v is None:
        raise invalid_request(f"missing required field: {field}")
    if not isinstance(v, str) or v not in allowed:
        raise invalid_request(f"field {field} must be one of {sorted(allowed)}")
    return v


def optional_enum(data, field, allowed, default=None):
    v = data.get(field)
    if v is None:
        return default
    if not isinstance(v, str) or v not in allowed:
        raise invalid_request(f"field {field} must be one of {sorted(allowed)}")
    return v


def optional_str_list(data, field):
    v = data.get(field)
    if v is None:
        return None
    if not isinstance(v, list) or not all(isinstance(x, str) for x in v):
        raise invalid_request(f"field {field} must be a list of strings")
    return v
