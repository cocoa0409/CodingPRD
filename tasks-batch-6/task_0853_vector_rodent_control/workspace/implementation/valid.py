"""Ladder step 5 helpers: request shape (PRD 2.5 step 5, ERR_VALIDATION 400).

Also the shared pagination reader of PRD 2.3.
"""

from flask import request

import lclock
from errors import ApiError

MISSING = object()


def bad(message):
    raise ApiError("ERR_VALIDATION", message)


def body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        bad("Request body must be a JSON object.")
    return data


def req_str(data, field, min_len=1, max_len=None):
    value = data.get(field, MISSING)
    if value is MISSING or value is None:
        bad("Field '%s' is required." % field)
    if not isinstance(value, str):
        bad("Field '%s' must be a string." % field)
    if len(value) < min_len:
        bad("Field '%s' is shorter than %d characters." % (field, min_len))
    if max_len is not None and len(value) > max_len:
        bad("Field '%s' is longer than %d characters." % (field, max_len))
    return value


def opt_str(data, field, default=None, min_len=0, max_len=None):
    if field not in data or data.get(field) is None:
        return default
    return req_str(data, field, min_len=min_len, max_len=max_len)


def req_enum(data, field, members):
    value = data.get(field, MISSING)
    if value is MISSING or value is None:
        bad("Field '%s' is required." % field)
    if not isinstance(value, str) or value not in members:
        bad("Field '%s' must be one of %s." % (field, ", ".join(members)))
    return value


def opt_enum(data, field, members, default=None):
    if field not in data or data.get(field) is None:
        return default
    return req_enum(data, field, members)


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def req_int(data, field, minimum=None, maximum=None):
    value = data.get(field, MISSING)
    if value is MISSING or value is None:
        bad("Field '%s' is required." % field)
    if not _is_int(value):
        bad("Field '%s' must be an integer." % field)
    if minimum is not None and value < minimum:
        bad("Field '%s' must be >= %d." % (field, minimum))
    if maximum is not None and value > maximum:
        bad("Field '%s' must be <= %d." % (field, maximum))
    return value


def opt_int(data, field, default=None, minimum=None, maximum=None):
    if field not in data or data.get(field) is None:
        return default
    return req_int(data, field, minimum=minimum, maximum=maximum)


def req_bool(data, field):
    value = data.get(field, MISSING)
    if value is MISSING or value is None:
        bad("Field '%s' is required." % field)
    if not isinstance(value, bool):
        bad("Field '%s' must be a boolean." % field)
    return value


def opt_bool(data, field, default=None):
    if field not in data or data.get(field) is None:
        return default
    return req_bool(data, field)


def req_dt(data, field):
    value = data.get(field, MISSING)
    if value is MISSING or value is None:
        bad("Field '%s' is required." % field)
    try:
        return lclock.parse(value)
    except ValueError:
        bad("Field '%s' must be an ISO 8601 UTC timestamp." % field)


def req_id(data, field):
    """A foreign key: required, must be a non-empty string."""
    value = data.get(field, MISSING)
    if value is MISSING or value is None:
        bad("Field '%s' is required." % field)
    if not isinstance(value, str) or not value:
        bad("Field '%s' must be a string identifier." % field)
    return value


def req_str_array(data, field, min_items=0):
    value = data.get(field, MISSING)
    if value is MISSING or value is None:
        bad("Field '%s' is required." % field)
    if not isinstance(value, list):
        bad("Field '%s' must be an array." % field)
    for item in value:
        if not isinstance(item, str):
            bad("Field '%s' must be an array of strings." % field)
    if len(value) < min_items:
        bad("Field '%s' must contain at least %d element(s)." % (field, min_items))
    return list(value)


def opt_str_array(data, field, default=None):
    if field not in data or data.get(field) is None:
        return list(default) if default is not None else []
    return req_str_array(data, field)


def req_decimal_hours(data, field):
    """A positive number carried to at most two decimal places."""
    from decimal import Decimal, InvalidOperation

    value = data.get(field, MISSING)
    if value is MISSING or value is None:
        bad("Field '%s' is required." % field)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        bad("Field '%s' must be a number." % field)
    try:
        dec = Decimal(str(value))
    except InvalidOperation:
        bad("Field '%s' must be a number." % field)
    if dec <= 0:
        bad("Field '%s' must be greater than zero." % field)
    if -dec.as_tuple().exponent > 2:
        bad("Field '%s' may carry at most two decimal places." % field)
    return dec


# --- pagination (PRD 2.3) ------------------------------------------------

LIMIT_DEFAULT = 10
LIMIT_MIN = 1
LIMIT_MAX = 100
OFFSET_DEFAULT = 0


def pagination():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit = LIMIT_DEFAULT
    offset = OFFSET_DEFAULT
    if raw_limit is not None and raw_limit != "":
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            bad("limit must be an integer.")
        if limit < LIMIT_MIN or limit > LIMIT_MAX:
            bad("limit must be between %d and %d." % (LIMIT_MIN, LIMIT_MAX))
    if raw_offset is not None and raw_offset != "":
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            bad("offset must be an integer.")
        if offset < 0:
            bad("offset must be zero or greater.")
    return limit, offset


def query_enum(name, members):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    if value not in members:
        bad("%s must be one of %s." % (name, ", ".join(members)))
    return value


def query_str(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    return value


def query_bool(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    lowered = value.lower()
    if lowered in ("true", "1"):
        return True
    if lowered in ("false", "0"):
        return False
    bad("%s must be a boolean." % name)
