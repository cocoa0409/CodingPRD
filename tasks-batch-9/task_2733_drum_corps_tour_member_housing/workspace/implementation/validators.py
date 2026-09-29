"""Rung 3-6 request-body validation helpers (PRD 2.6).

Rung 3  -- required fields present, declared JSON type, declared enum member;
           integer cent fields must arrive as JSON integers.
Rung 4  -- ordered date/instant pairs strictly increasing.
Rung 5  -- conditionally required fields obey their condition.
Rung 6  -- monetary/count/placement positivity floors.
"""
from flask import request

from errors import ApiError
from store import parse_date, parse_instant


def get_body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError("ERR_INVALID_REQUEST", "The request body must be a JSON object.")
    return data


def _bad(field, detail):
    raise ApiError("ERR_INVALID_REQUEST", "Field '%s' %s." % (field, detail))


def present(body, field):
    return field in body and body[field] is not None


def is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def req_str(body, field):
    if not present(body, field):
        _bad(field, "is required")
    value = body[field]
    if not isinstance(value, str):
        _bad(field, "must be a string")
    return value


def opt_str(body, field, default=None):
    if not present(body, field):
        return default
    value = body[field]
    if not isinstance(value, str):
        _bad(field, "must be a string")
    return value


def req_int(body, field):
    if not present(body, field):
        _bad(field, "is required")
    value = body[field]
    if not is_int(value):
        _bad(field, "must be a JSON integer")
    return value


def opt_int(body, field, default=None):
    if not present(body, field):
        return default
    value = body[field]
    if not is_int(value):
        _bad(field, "must be a JSON integer")
    return value


def req_number(body, field):
    if not present(body, field):
        _bad(field, "is required")
    value = body[field]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _bad(field, "must be a number")
    return value


def req_bool(body, field):
    if not present(body, field):
        _bad(field, "is required")
    value = body[field]
    if not isinstance(value, bool):
        _bad(field, "must be a boolean")
    return value


def req_enum(body, field, allowed):
    value = req_str(body, field)
    if value not in allowed:
        _bad(field, "must be one of %s" % ", ".join(allowed))
    return value


def opt_enum(body, field, allowed, default=None):
    if not present(body, field):
        return default
    value = req_str(body, field)
    if value not in allowed:
        _bad(field, "must be one of %s" % ", ".join(allowed))
    return value


def req_date(body, field):
    """Return (raw_string, date).  Dates echo back verbatim."""
    raw = req_str(body, field)
    parsed = parse_date(raw)
    if parsed is None:
        _bad(field, "must be a YYYY-MM-DD calendar date")
    return raw, parsed


def req_instant(body, field):
    """Return (raw_string, datetime).  Instants echo back verbatim."""
    raw = req_str(body, field)
    parsed = parse_instant(raw)
    if parsed is None:
        _bad(field, "must be an ISO 8601 UTC instant")
    return raw, parsed


def opt_instant(body, field):
    if not present(body, field):
        return None, None
    return req_instant(body, field)


def check(condition, field, detail):
    if not condition:
        _bad(field, detail)


def positive(condition, message):
    """Rung 6 -- ERR_AMOUNT_NOT_POSITIVE."""
    if not condition:
        raise ApiError("ERR_AMOUNT_NOT_POSITIVE", message)


def date_range(condition, message):
    """Rung 4 -- ERR_INVALID_DATE_RANGE."""
    if not condition:
        raise ApiError("ERR_INVALID_DATE_RANGE", message)


def conditional(condition, message):
    """Rung 5 -- ERR_CONDITIONAL_FIELD_MISMATCH."""
    if not condition:
        raise ApiError("ERR_CONDITIONAL_FIELD_MISMATCH", message)


# --------------------------------------------------------------------------
# list-endpoint query filters
# --------------------------------------------------------------------------
def arg_str(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    return value


def arg_int(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        raise ApiError("ERR_INVALID_REQUEST", "Query parameter '%s' must be an integer." % name)


def arg_bool(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    lowered = value.strip().lower()
    if lowered in ("true", "1", "yes"):
        return True
    if lowered in ("false", "0", "no"):
        return False
    raise ApiError("ERR_INVALID_REQUEST", "Query parameter '%s' must be a boolean." % name)
