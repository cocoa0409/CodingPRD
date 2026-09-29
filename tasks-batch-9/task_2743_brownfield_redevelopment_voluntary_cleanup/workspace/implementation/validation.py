"""Request-shape validation (PRD section 2.10 priority 3).

Every failure here raises ERR_INVALID_REQUEST (HTTP 422).
"""

from decimal import Decimal, InvalidOperation

from flask import request

import db
from errors import ApiError

MISSING = object()


def fail(message):
    raise ApiError("ERR_INVALID_REQUEST", message)


def json_body():
    data = request.get_json(silent=True)
    if data is None:
        if request.data and request.data.strip():
            fail("Request body must be a JSON object.")
        return {}
    if not isinstance(data, dict):
        fail("Request body must be a JSON object.")
    return data


def present(body, name):
    return name in body and body[name] is not None


def _get(body, name, required):
    if name not in body or body[name] is None:
        if required:
            fail("Field %s is required." % name)
        return MISSING
    return body[name]


def string_field(body, name, required=True, min_len=1, max_len=None,
                 upper=False, default=None):
    value = _get(body, name, required)
    if value is MISSING:
        return default
    if not isinstance(value, str):
        fail("Field %s must be a string." % name)
    if len(value) < min_len:
        fail("Field %s must be at least %d characters." % (name, min_len))
    if max_len is not None and len(value) > max_len:
        fail("Field %s must be at most %d characters." % (name, max_len))
    if upper and value != value.upper():
        fail("Field %s must be uppercase." % name)
    return value


def enum_field(body, name, values, required=True, default=None):
    value = _get(body, name, required)
    if value is MISSING:
        return default
    if not isinstance(value, str) or value not in values:
        fail("Field %s must be one of %s." % (name, ", ".join(values)))
    return value


def bool_field(body, name, required=False, default=None):
    value = _get(body, name, required)
    if value is MISSING:
        return default
    if not isinstance(value, bool):
        fail("Field %s must be a boolean." % name)
    return value


def int_field(body, name, required=True, minimum=None, maximum=None, default=None):
    value = _get(body, name, required)
    if value is MISSING:
        return default
    if isinstance(value, bool) or not isinstance(value, int):
        fail("Field %s must be an integer." % name)
    if minimum is not None and value < minimum:
        fail("Field %s must be >= %s." % (name, minimum))
    if maximum is not None and value > maximum:
        fail("Field %s must be <= %s." % (name, maximum))
    return value


def number_field(body, name, required=True, gt=None, ge=None, le=None,
                 max_dp=None, default=None):
    value = _get(body, name, required)
    if value is MISSING:
        return default
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        fail("Field %s must be a number." % name)
    try:
        dec = Decimal(str(value))
    except InvalidOperation:
        fail("Field %s must be a number." % name)
    if not dec.is_finite():
        fail("Field %s must be a finite number." % name)
    if gt is not None and dec <= Decimal(str(gt)):
        fail("Field %s must be > %s." % (name, gt))
    if ge is not None and dec < Decimal(str(ge)):
        fail("Field %s must be >= %s." % (name, ge))
    if le is not None and dec > Decimal(str(le)):
        fail("Field %s must be <= %s." % (name, le))
    if max_dp is not None:
        exponent = dec.normalize().as_tuple().exponent
        if isinstance(exponent, int) and exponent < -max_dp:
            fail("Field %s allows at most %d decimal places." % (name, max_dp))
    return value


def date_field(body, name, required=True, default=None):
    value = _get(body, name, required)
    if value is MISSING:
        return default
    parsed = db.parse_date(value)
    if parsed is None:
        fail("Field %s must be an ISO 8601 date (YYYY-MM-DD)." % name)
    return parsed


def datetime_field(body, name, required=True, default=None):
    value = _get(body, name, required)
    if value is MISSING:
        return default
    parsed = db.parse_datetime(value)
    if parsed is None:
        fail("Field %s must be an ISO 8601 datetime." % name)
    return parsed


def array_field(body, name, required=True, min_len=1, max_len=None, default=None):
    value = _get(body, name, required)
    if value is MISSING:
        return default
    if not isinstance(value, list):
        fail("Field %s must be an array." % name)
    if min_len is not None and len(value) < min_len:
        fail("Field %s must contain at least %d element(s)." % (name, min_len))
    if max_len is not None and len(value) > max_len:
        fail("Field %s must contain at most %d element(s)." % (name, max_len))
    return value


def enum_array_field(body, name, values, required=True, min_len=1, max_len=None,
                     unique=False, default=None):
    items = array_field(body, name, required=required, min_len=min_len,
                        max_len=max_len, default=MISSING)
    if items is MISSING:
        return default
    for item in items:
        if not isinstance(item, str) or item not in values:
            fail("Field %s elements must each be one of %s."
                 % (name, ", ".join(values)))
    if unique and len(set(items)) != len(items):
        fail("Field %s elements must be unique." % name)
    return list(items)


def id_field(body, name, required=True, default=None):
    value = _get(body, name, required)
    if value is MISSING:
        return default
    if not isinstance(value, str) or not value.strip():
        fail("Field %s must be a non-empty string identifier." % name)
    return value


# ------------------------------------------------------------ query filters


def query_enum(name, values):
    if name not in request.args:
        return None
    value = request.args.get(name)
    if value is None or value == "":
        fail("Query parameter %s must be one of %s." % (name, ", ".join(values)))
    if value not in values:
        fail("Query parameter %s must be one of %s." % (name, ", ".join(values)))
    return value


def query_string(name):
    if name not in request.args:
        return None
    value = request.args.get(name)
    if value is None or value == "":
        fail("Query parameter %s must be a non-empty string." % name)
    return value
