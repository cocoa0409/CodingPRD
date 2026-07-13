"""Request well-formedness helpers (priority 6 -> ERR_INVALID_REQUEST 400)."""

import re
from decimal import Decimal, InvalidOperation

from flask import request

from errors import err

HHMM = re.compile(r"^([01][0-9]|2[0-3]):[0-5][0-9]$")

SITES = ("GOOGLE", "YELP", "FACEBOOK")
CHANNELS = ("SMS", "EMAIL")
PLAN_TIERS = ("BASIC", "PRO", "ENTERPRISE")
SYNC_OUTCOMES = ("SUCCESS", "FAILURE")
EVENT_TYPES = ("DELIVERED", "CLICKED", "FAILED")


def body():
    if not request.data:
        return {}
    payload = request.get_json(silent=True)
    if payload is None:
        raise err("ERR_INVALID_REQUEST", "Request body is not valid JSON.")
    if not isinstance(payload, dict):
        raise err("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return payload


def _bad(field, why):
    raise err("ERR_INVALID_REQUEST", "Field '%s' %s." % (field, why))


def req_str(data, field):
    if field not in data or data[field] is None:
        _bad(field, "is required")
    value = data[field]
    if not isinstance(value, str):
        _bad(field, "must be a string")
    return value


def opt_str(data, field, default=None):
    if field not in data or data[field] is None:
        return default
    value = data[field]
    if not isinstance(value, str):
        _bad(field, "must be a string")
    return value


def req_int(data, field, minimum=None, maximum=None):
    if field not in data or data[field] is None:
        _bad(field, "is required")
    value = data[field]
    if isinstance(value, bool) or not isinstance(value, int):
        _bad(field, "must be an integer")
    if minimum is not None and value < minimum:
        _bad(field, "must be >= %s" % minimum)
    if maximum is not None and value > maximum:
        _bad(field, "must be <= %s" % maximum)
    return value


def opt_int(data, field, default=None, minimum=None, maximum=None):
    if field not in data or data[field] is None:
        return default
    return req_int(data, field, minimum, maximum)


def req_bool(data, field):
    if field not in data or data[field] is None:
        _bad(field, "is required")
    value = data[field]
    if not isinstance(value, bool):
        _bad(field, "must be a boolean")
    return value


def opt_bool(data, field, default=None):
    if field not in data or data[field] is None:
        return default
    return req_bool(data, field)


def req_enum(data, field, members):
    value = req_str(data, field)
    if value not in members:
        _bad(field, "must be one of %s" % (", ".join(members)))
    return value


def opt_enum(data, field, members, default=None):
    if field not in data or data[field] is None:
        return default
    return req_enum(data, field, members)


def req_decimal(data, field, minimum=None, maximum=None):
    if field not in data or data[field] is None:
        _bad(field, "is required")
    value = data[field]
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        _bad(field, "must be a number")
    try:
        dec = Decimal(str(value))
    except (InvalidOperation, ValueError):
        _bad(field, "must be a number")
    if not dec.is_finite():
        _bad(field, "must be a finite number")
    if minimum is not None and dec < minimum:
        _bad(field, "must be >= %s" % minimum)
    if maximum is not None and dec > maximum:
        _bad(field, "must be <= %s" % maximum)
    return dec


def req_hhmm(data, field):
    value = req_str(data, field)
    if not HHMM.match(value):
        _bad(field, "must be an HH:MM 24-hour time")
    return value


def minutes(hhmm):
    hours, mins = hhmm.split(":")
    return int(hours) * 60 + int(mins)


def req_datetime(data, field):
    from store import parse_dt
    value = req_str(data, field)
    parsed = parse_dt(value)
    if parsed is None:
        _bad(field, "must be an ISO-8601 instant")
    return parsed


def enum_filter(field, members):
    """Read an optional query-string enum filter."""
    value = request.args.get(field)
    if value is None:
        return None
    if value not in members:
        _bad(field, "must be one of %s" % (", ".join(members)))
    return value
