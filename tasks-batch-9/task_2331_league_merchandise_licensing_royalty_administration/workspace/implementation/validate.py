"""Scalar shape validation helpers (global rules 7-9). Every failure is ERR_VALIDATION."""

import db
from errors import ApiError

MISSING = object()


def _bad(message):
    raise ApiError("ERR_VALIDATION", message)


def present(body, name):
    return name in body and body[name] is not None


def req_string(body, name, min_len=1, max_len=None):
    if not present(body, name):
        _bad("%s is required." % name)
    value = body[name]
    if not isinstance(value, str):
        _bad("%s must be a string." % name)
    if len(value) < min_len:
        _bad("%s must be at least %d characters." % (name, min_len))
    if max_len is not None and len(value) > max_len:
        _bad("%s must be at most %d characters." % (name, max_len))
    return value


def opt_string(body, name, default=None, min_len=1, max_len=None):
    if not present(body, name):
        return default
    return req_string(body, name, min_len, max_len)


def req_int(body, name):
    if not present(body, name):
        _bad("%s is required." % name)
    value = body[name]
    if isinstance(value, bool) or not isinstance(value, int):
        _bad("%s must be an integer." % name)
    return value


def opt_int(body, name, default=None):
    if not present(body, name):
        return default
    return req_int(body, name)


def req_bool(body, name):
    if not present(body, name):
        _bad("%s is required." % name)
    value = body[name]
    if not isinstance(value, bool):
        _bad("%s must be a boolean." % name)
    return value


def opt_bool(body, name, default=None):
    if not present(body, name):
        return default
    return req_bool(body, name)


def req_enum(body, name, allowed):
    value = req_string(body, name)
    if value not in allowed:
        _bad("%s must be one of %s." % (name, ", ".join(sorted(allowed))))
    return value


def opt_enum(body, name, allowed, default=None):
    if not present(body, name):
        return default
    return req_enum(body, name, allowed)


def req_cents(body, name):
    value = req_int(body, name)
    if value < 0:
        _bad("%s must be at least 0." % name)
    return value


def opt_cents(body, name, default=None):
    if not present(body, name):
        return default
    return req_cents(body, name)


def req_bps(body, name):
    value = req_int(body, name)
    if value < 0 or value > 10000:
        _bad("%s must be between 0 and 10000." % name)
    return value


def opt_bps(body, name, default=None):
    if not present(body, name):
        return default
    return req_bps(body, name)


def req_units(body, name):
    value = req_int(body, name)
    if value < 1:
        _bad("%s must be at least 1." % name)
    return value


def req_quarter(body, name):
    value = req_string(body, name)
    if not db.is_quarter(value):
        _bad("%s must be a fiscal quarter label such as 2026Q2." % name)
    return value


def opt_quarter(body, name, default=None):
    if not present(body, name):
        return default
    return req_quarter(body, name)


def req_date(body, name):
    value = req_string(body, name)
    parsed = db.parse_date(value)
    if parsed is None:
        _bad("%s must be a calendar date formatted YYYY-MM-DD." % name)
    return parsed


def req_instant(body, name):
    value = req_string(body, name)
    parsed = db.parse_instant(value)
    if parsed is None:
        _bad("%s must be an RFC 3339 instant with a Z offset." % name)
    return parsed


def req_list(body, name, min_len=1, max_len=None):
    if not present(body, name):
        _bad("%s is required." % name)
    value = body[name]
    if not isinstance(value, list):
        _bad("%s must be an array." % name)
    if len(value) < min_len:
        _bad("%s must have at least %d entries." % (name, min_len))
    if max_len is not None and len(value) > max_len:
        _bad("%s must have at most %d entries." % (name, max_len))
    return value


def req_string_list(body, name, min_len=1, max_len=None, distinct=True):
    items = req_list(body, name, min_len, max_len)
    for item in items:
        if not isinstance(item, str) or item == "":
            _bad("%s entries must be non-empty strings." % name)
    if distinct and len(set(items)) != len(items):
        _bad("%s entries must be distinct." % name)
    return items


def quarter_sequence(body, name, min_len=1, max_len=None):
    """Non-empty array of distinct, consecutive, ascending quarter labels."""
    items = req_list(body, name, min_len, max_len)
    for item in items:
        if not db.is_quarter(item):
            _bad("%s entries must be fiscal quarter labels." % name)
    if len(set(items)) != len(items):
        _bad("%s entries must be distinct." % name)
    for i in range(1, len(items)):
        if db.elapsed_quarters(items[i - 1], items[i]) != 1:
            _bad("%s must be consecutive quarters in ascending order." % name)
    return items
