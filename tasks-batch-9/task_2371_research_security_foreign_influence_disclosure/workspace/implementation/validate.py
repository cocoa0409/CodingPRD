"""Request-shape helpers (order step 6) and pagination (PRD 2.3)."""

from decimal import Decimal

from flask import request

import util
from errors import ApiError

MISSING = object()


def body():
    """The JSON body as a dict; a missing or non-object body reads as empty."""
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return {}
    return data


def bad(message):
    raise ApiError("ERR_INVALID_REQUEST", message)


# --------------------------------------------------------------- primitives

def req_string(data, name):
    value = data.get(name, MISSING)
    if value is MISSING or value is None:
        bad("Field '%s' is required." % name)
    if not isinstance(value, str) or not value.strip():
        bad("Field '%s' must be a non-empty string." % name)
    return value


def opt_string(data, name, default=None):
    value = data.get(name, MISSING)
    if value is MISSING or value is None:
        return default
    if not isinstance(value, str) or not value.strip():
        bad("Field '%s' must be a non-empty string." % name)
    return value


def req_enum(data, name, members):
    value = req_string(data, name)
    if value not in members:
        bad("Field '%s' must be one of %s." % (name, ", ".join(members)))
    return value


def opt_enum(data, name, members, default=None):
    value = data.get(name, MISSING)
    if value is MISSING or value is None:
        return default
    if not isinstance(value, str) or value not in members:
        bad("Field '%s' must be one of %s." % (name, ", ".join(members)))
    return value


def req_id(data, name):
    """A reference field: must be present and a non-empty string."""
    return req_string(data, name)


def opt_id(data, name):
    value = data.get(name, MISSING)
    if value is MISSING or value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        bad("Field '%s' must be a non-empty string identifier." % name)
    return value


def req_bool(data, name):
    value = data.get(name, MISSING)
    if value is MISSING or value is None:
        bad("Field '%s' is required." % name)
    if not isinstance(value, bool):
        bad("Field '%s' must be a boolean." % name)
    return value


def opt_bool(data, name, default=None):
    value = data.get(name, MISSING)
    if value is MISSING or value is None:
        return default
    if not isinstance(value, bool):
        bad("Field '%s' must be a boolean." % name)
    return value


def _as_number(data, name, value):
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        bad("Field '%s' must be a number." % name)
    number = util.dec(value)
    if number is None:
        bad("Field '%s' must be a number." % name)
    return number


def req_int(data, name, minimum=None, maximum=None):
    value = data.get(name, MISSING)
    if value is MISSING or value is None:
        bad("Field '%s' is required." % name)
    if isinstance(value, bool) or not isinstance(value, int):
        if isinstance(value, float) and float(value).is_integer():
            value = int(value)
        else:
            bad("Field '%s' must be an integer." % name)
    _range(name, util.dec(value), minimum, maximum)
    return int(value)


def opt_int(data, name, minimum=None, maximum=None, default=None):
    value = data.get(name, MISSING)
    if value is MISSING or value is None:
        return default
    return req_int(data, name, minimum, maximum)


def req_decimal(data, name, minimum=None, maximum=None, exclusive_min=None,
                max_places=None):
    value = data.get(name, MISSING)
    if value is MISSING or value is None:
        bad("Field '%s' is required." % name)
    number = _as_number(data, name, value)
    if max_places is not None and util.decimal_places(number) > max_places:
        bad("Field '%s' allows at most %d decimal places." % (name, max_places))
    _range(name, number, minimum, maximum, exclusive_min)
    return number


def opt_decimal(data, name, minimum=None, maximum=None, exclusive_min=None,
                max_places=None, default=None):
    value = data.get(name, MISSING)
    if value is MISSING or value is None:
        return default
    return req_decimal(data, name, minimum, maximum, exclusive_min, max_places)


def _range(name, number, minimum, maximum, exclusive_min=None):
    if minimum is not None and number < util.dec(minimum):
        bad("Field '%s' must be at least %s." % (name, minimum))
    if exclusive_min is not None and number <= util.dec(exclusive_min):
        bad("Field '%s' must be greater than %s." % (name, exclusive_min))
    if maximum is not None and number > util.dec(maximum):
        bad("Field '%s' must be at most %s." % (name, maximum))


def req_instant(data, name):
    value = req_string(data, name)
    if util.parse_dt(value) is None:
        bad("Field '%s' must be an ISO-8601 instant." % name)
    return value


def opt_instant(data, name, default=None):
    value = data.get(name, MISSING)
    if value is MISSING or value is None:
        return default
    return req_instant(data, name)


def req_country_code(data, name):
    value = req_string(data, name)
    if len(value) != 2 or not value.isalpha() or value != value.upper():
        bad("Field '%s' must be exactly two uppercase letters." % name)
    return value


def opt_enum_list(data, name, members, default=None):
    value = data.get(name, MISSING)
    if value is MISSING or value is None:
        return default
    if not isinstance(value, list):
        bad("Field '%s' must be a list." % name)
    for entry in value:
        if not isinstance(entry, str) or entry not in members:
            bad("Field '%s' entries must be one of %s."
                % (name, ", ".join(members)))
    return list(value)


def no_body_fields():
    """Endpoints declaring an empty input list take no payload."""
    return None


# --------------------------------------------------------------- pagination

def pagination():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit = 10
    offset = 0
    if raw_limit is not None:
        try:
            limit = int(str(raw_limit).strip())
        except (TypeError, ValueError):
            bad("Query parameter 'limit' must be an integer.")
        if limit < 1 or limit > 100:
            bad("Query parameter 'limit' must be between 1 and 100.")
    if raw_offset is not None:
        try:
            offset = int(str(raw_offset).strip())
        except (TypeError, ValueError):
            bad("Query parameter 'offset' must be an integer.")
        if offset < 0:
            bad("Query parameter 'offset' must be at least 0.")
    return limit, offset


def filter_enum(name, members):
    value = request.args.get(name)
    if value is None:
        return None
    value = value.strip()
    if not value:
        return None
    if value not in members:
        bad("Query parameter '%s' must be one of %s." % (name, ", ".join(members)))
    return value


def filter_value(name):
    value = request.args.get(name)
    if value is None:
        return None
    value = value.strip()
    return value or None
