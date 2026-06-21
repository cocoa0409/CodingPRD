"""Body-field validation helpers.

Two distinct error surfaces (PRD §2.8):
  - presence / type / enum validity  -> ERR_INVALID_REQUEST (400)
  - numeric range violations         -> ERR_VALIDATION_AMOUNT (422)

Range checks are enforced AFTER presence/type/enum on the same field, so a
missing field reports ERR_INVALID_REQUEST and a present-but-out-of-range field
reports ERR_VALIDATION_AMOUNT.
"""
from errors import err, ERR_INVALID_REQUEST, ERR_VALIDATION_AMOUNT


def get_body():
    from flask import request
    data = request.get_json(silent=True)
    if data is None or not isinstance(data, dict):
        return {}
    return data


def require_str(body, field):
    if field not in body or body[field] is None:
        raise err(ERR_INVALID_REQUEST, "Missing required field: %s" % field)
    v = body[field]
    if not isinstance(v, str) or v == "":
        raise err(ERR_INVALID_REQUEST, "Field %s must be a non-empty string" % field)
    return v


def require_int(body, field):
    if field not in body or body[field] is None:
        raise err(ERR_INVALID_REQUEST, "Missing required field: %s" % field)
    v = body[field]
    # bool is a subclass of int; reject it explicitly.
    if isinstance(v, bool) or not isinstance(v, int):
        raise err(ERR_INVALID_REQUEST, "Field %s must be an integer" % field)
    return v


def require_number(body, field):
    if field not in body or body[field] is None:
        raise err(ERR_INVALID_REQUEST, "Missing required field: %s" % field)
    v = body[field]
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise err(ERR_INVALID_REQUEST, "Field %s must be a number" % field)
    return v


def require_enum(body, field, members):
    v = require_str(body, field)
    if v not in members:
        raise err(ERR_INVALID_REQUEST,
                  "Field %s must be one of %s" % (field, sorted(members)))
    return v


def amount_positive(value, field):
    """Range: value must be > 0 (ERR_VALIDATION_AMOUNT)."""
    if value <= 0:
        raise err(ERR_VALIDATION_AMOUNT, "Field %s must be positive" % field)
    return value


def amount_nonnegative(value, field):
    if value < 0:
        raise err(ERR_VALIDATION_AMOUNT, "Field %s must be >= 0" % field)
    return value


def range_inclusive(value, field, low, high):
    if value < low or value > high:
        raise err(ERR_VALIDATION_AMOUNT,
                  "Field %s must be within [%s, %s]" % (field, low, high))
    return value


def factor_range(value, field):
    # 0 < value <= 1
    if not (value > 0 and value <= 1):
        raise err(ERR_VALIDATION_AMOUNT, "Field %s must be in (0, 1]" % field)
    return value
