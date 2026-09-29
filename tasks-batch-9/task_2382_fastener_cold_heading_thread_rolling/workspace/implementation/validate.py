"""Schema-tier validation helpers.  Every failure raises ERR_VALIDATION (400)."""

from decimal import Decimal

from flask import request

from errors import ApiError
from util import dec, parse_dt

_MISSING = object()


def _fail(message):
    raise ApiError("ERR_VALIDATION", message)


def _present(body, name, required):
    if name not in body or body[name] is None:
        if required:
            _fail("Field '%s' is required." % name)
        return _MISSING
    return body[name]


# --------------------------------------------------------------------------
# strings
# --------------------------------------------------------------------------

def field_str(body, name, required=True, default=None, allow_empty=False):
    value = _present(body, name, required)
    if value is _MISSING:
        return default
    if not isinstance(value, str):
        _fail("Field '%s' must be a string." % name)
    if not allow_empty and value.strip() == "":
        _fail("Field '%s' must not be empty." % name)
    return value


def field_enum(body, name, allowed, required=True, default=None):
    value = _present(body, name, required)
    if value is _MISSING:
        return default
    if not isinstance(value, str) or value not in allowed:
        _fail("Field '%s' must be one of %s." % (name, sorted(allowed)))
    return value


def field_bool(body, name, required=True, default=None):
    value = _present(body, name, required)
    if value is _MISSING:
        return default
    if not isinstance(value, bool):
        _fail("Field '%s' must be a boolean." % name)
    return value


# --------------------------------------------------------------------------
# numbers
# --------------------------------------------------------------------------

def field_int(body, name, required=True, default=None, minimum=None, maximum=None):
    value = _present(body, name, required)
    if value is _MISSING:
        return default
    if isinstance(value, bool):
        _fail("Field '%s' must be an integer." % name)
    if isinstance(value, int):
        result = value
    elif isinstance(value, Decimal):
        if value != value.to_integral_value():
            _fail("Field '%s' must be an integer." % name)
        result = int(value)
    else:
        _fail("Field '%s' must be an integer." % name)
    if minimum is not None and result < minimum:
        _fail("Field '%s' must be >= %s." % (name, minimum))
    if maximum is not None and result > maximum:
        _fail("Field '%s' must be <= %s." % (name, maximum))
    return result


def field_num(body, name, required=True, default=None, minimum=None, maximum=None,
              exclusive_min=None, exclusive_max=None):
    value = _present(body, name, required)
    if value is _MISSING:
        return default
    if isinstance(value, bool) or not isinstance(value, (int, Decimal)):
        _fail("Field '%s' must be a number." % name)
    result = dec(value)
    if minimum is not None and result < dec(minimum):
        _fail("Field '%s' must be >= %s." % (name, minimum))
    if maximum is not None and result > dec(maximum):
        _fail("Field '%s' must be <= %s." % (name, maximum))
    if exclusive_min is not None and result <= dec(exclusive_min):
        _fail("Field '%s' must be > %s." % (name, exclusive_min))
    if exclusive_max is not None and result >= dec(exclusive_max):
        _fail("Field '%s' must be < %s." % (name, exclusive_max))
    return result


# --------------------------------------------------------------------------
# datetimes
# --------------------------------------------------------------------------

def field_dt(body, name, required=True, default=None):
    value = _present(body, name, required)
    if value is _MISSING:
        return default
    parsed = parse_dt(value)
    if parsed is None:
        _fail("Field '%s' must be an ISO-8601 UTC datetime." % name)
    return parsed


# --------------------------------------------------------------------------
# arrays
# --------------------------------------------------------------------------

def field_enum_list(body, name, allowed, required=True, default=None,
                    non_empty=True, must_contain=None):
    value = _present(body, name, required)
    if value is _MISSING:
        return list(default) if default is not None else None
    if not isinstance(value, list):
        _fail("Field '%s' must be an array." % name)
    if non_empty and not value:
        _fail("Field '%s' must not be empty." % name)
    for item in value:
        if not isinstance(item, str) or item not in allowed:
            _fail("Field '%s' entries must be one of %s." % (name, sorted(allowed)))
    if must_contain is not None and must_contain not in value:
        _fail("Field '%s' must contain %s." % (name, must_contain))
    return list(value)


# --------------------------------------------------------------------------
# query string
# --------------------------------------------------------------------------

LIMIT_DEFAULT = 10
LIMIT_MIN = 1
LIMIT_MAX = 100
OFFSET_DEFAULT = 0


def _query_int(name, default, minimum, maximum):
    raw = request.args.get(name)
    if raw is None:
        return default
    raw = raw.strip()
    if raw == "":
        _fail("Query parameter '%s' must be an integer." % name)
    try:
        value = int(raw, 10)
    except ValueError:
        _fail("Query parameter '%s' must be an integer." % name)
    if minimum is not None and value < minimum:
        _fail("Query parameter '%s' must be >= %s." % (name, minimum))
    if maximum is not None and value > maximum:
        _fail("Query parameter '%s' must be <= %s." % (name, maximum))
    return value


def pagination():
    limit = _query_int("limit", LIMIT_DEFAULT, LIMIT_MIN, LIMIT_MAX)
    offset = _query_int("offset", OFFSET_DEFAULT, 0, None)
    return limit, offset


def query_enum(name, allowed):
    raw = request.args.get(name)
    if raw is None:
        return None
    if raw not in allowed:
        _fail("Query parameter '%s' must be one of %s." % (name, sorted(allowed)))
    return raw


def query_str(name):
    raw = request.args.get(name)
    if raw is None:
        return None
    return raw


def paginate(records, limit, offset):
    total = len(records)
    return records[offset:offset + limit], total
