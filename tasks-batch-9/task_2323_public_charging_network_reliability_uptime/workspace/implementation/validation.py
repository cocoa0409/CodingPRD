"""Request-shape validation (PRD §2.11 step 5) and pagination parsing (§2.3).

Every failure in this module is a request-shape failure and raises
ERR_INVALID_REQUEST (HTTP 400).
"""
from decimal import Decimal, InvalidOperation

from flask import request

import clock
from errors import err

MISSING = object()

PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0


def _bad(field, detail):
    return err("ERR_INVALID_REQUEST", "Field '%s' %s." % (field, detail))


def json_body():
    """The parsed JSON object, or {} when the client sent nothing at all."""
    if not request.data:
        return {}
    payload = request.get_json(silent=True)
    if payload is None:
        raise err("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    if not isinstance(payload, dict):
        raise err("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return payload


def _present(body, name):
    return name in body and body[name] is not None


def as_string(body, name, required=True, default=None, allow_empty=False):
    if not _present(body, name):
        if required:
            raise _bad(name, "is required")
        return default
    value = body[name]
    if not isinstance(value, str):
        raise _bad(name, "must be a string")
    if not allow_empty and value.strip() == "":
        raise _bad(name, "must be non-empty")
    return value


def fk(body, name):
    """A foreign key candidate for §2.11 step 3.  Returns the raw string when the
    field is a usable identifier; anything else is left to step 5 to reject."""
    if not _present(body, name):
        return None
    value = body[name]
    if not isinstance(value, str) or value.strip() == "":
        return None
    return value


def as_enum(body, name, allowed, required=True, default=None):
    if not _present(body, name):
        if required:
            raise _bad(name, "is required")
        return default
    value = body[name]
    if not isinstance(value, str) or value not in allowed:
        raise _bad(name, "must be one of %s" % ", ".join(allowed))
    return value


def as_bool(body, name, required=False, default=None):
    if not _present(body, name):
        if required:
            raise _bad(name, "is required")
        return default
    value = body[name]
    if not isinstance(value, bool):
        raise _bad(name, "must be a boolean")
    return value


def as_int(body, name, required=True, default=None, minimum=None, maximum=None,
           range_error=None):
    if not _present(body, name):
        if required:
            raise _bad(name, "is required")
        return default
    value = body[name]
    if isinstance(value, bool) or not isinstance(value, int):
        raise _bad(name, "must be an integer")
    if minimum is not None and value < minimum:
        if range_error:
            raise err(range_error, "Field '%s' must be at least %s." % (name, minimum))
        raise _bad(name, "must be at least %s" % minimum)
    if maximum is not None and value > maximum:
        if range_error:
            raise err(range_error, "Field '%s' must be at most %s." % (name, maximum))
        raise _bad(name, "must be at most %s" % maximum)
    return value


def as_number(body, name, required=True, default=None, minimum=None,
              exclusive_minimum=None, places=2):
    if not _present(body, name):
        if required:
            raise _bad(name, "is required")
        return default
    value = body[name]
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        raise _bad(name, "must be a number")
    try:
        number = Decimal(str(value))
    except InvalidOperation:
        raise _bad(name, "must be a number")
    if not number.is_finite():
        raise _bad(name, "must be a finite number")
    if minimum is not None and number < Decimal(str(minimum)):
        raise _bad(name, "must be at least %s" % minimum)
    if exclusive_minimum is not None and number <= Decimal(str(exclusive_minimum)):
        raise _bad(name, "must be greater than %s" % exclusive_minimum)
    if places == 2:
        from calc import q2
        return q2(number)
    if places == 3:
        from calc import q3
        return q3(number)
    return number


def as_datetime(body, name, required=True, default=None):
    if not _present(body, name):
        if required:
            raise _bad(name, "is required")
        return default
    value = body[name]
    if not isinstance(value, str):
        raise _bad(name, "must be an ISO 8601 timestamp string")
    parsed = clock.parse_datetime(value)
    if parsed is None:
        raise _bad(name, "must be an ISO 8601 timestamp string")
    return parsed


# --------------------------------------------------------------------- pagination
def pagination():
    limit = _query_int("limit", PAGINATION_DEFAULT_LIMIT)
    offset = _query_int("offset", PAGINATION_DEFAULT_OFFSET)
    if limit < PAGINATION_MIN_LIMIT or limit > PAGINATION_MAX_LIMIT:
        raise err("ERR_INVALID_REQUEST",
                  "Query parameter 'limit' must be between %d and %d."
                  % (PAGINATION_MIN_LIMIT, PAGINATION_MAX_LIMIT))
    if offset < 0:
        raise err("ERR_INVALID_REQUEST", "Query parameter 'offset' may not be negative.")
    return limit, offset


def _query_int(name, default):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    text = raw.strip()
    try:
        return int(text)
    except (TypeError, ValueError):
        raise err("ERR_INVALID_REQUEST", "Query parameter '%s' must be an integer." % name)


def filters(*names):
    """Exact-match domain filters taken from the query string."""
    selected = {}
    for name in names:
        raw = request.args.get(name)
        if raw is not None and raw != "":
            selected[name] = raw
    return selected


def apply_filters(rows, selected):
    result = rows
    for name, value in selected.items():
        result = [row for row in result if row.get(name) == value]
    return result
