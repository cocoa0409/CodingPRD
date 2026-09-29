"""Payload and query-string validation helpers.

Everything in here reports ERR_INVALID_REQUEST (400) -- band 5 of the order of
refusal.
"""

import db
from errors import ApiError

MISSING = object()


def bad(message):
    raise ApiError("ERR_INVALID_REQUEST", message)


def present(payload, key):
    return key in payload and payload[key] is not None


def req_str(payload, key, min_len=1, max_len=None):
    if not present(payload, key):
        bad("%s is required." % key)
    value = payload[key]
    if not isinstance(value, str):
        bad("%s must be a string." % key)
    if len(value) < min_len:
        bad("%s must be at least %d characters." % (key, min_len))
    if max_len is not None and len(value) > max_len:
        bad("%s may not exceed %d characters." % (key, max_len))
    return value


def opt_str(payload, key, min_len=1, max_len=None, default=None):
    if not present(payload, key):
        return default
    return req_str(payload, key, min_len, max_len)


def req_enum(payload, key, allowed):
    value = req_str(payload, key)
    if value not in allowed:
        bad("%s must be one of %s." % (key, ", ".join(sorted(allowed))))
    return value


def opt_enum(payload, key, allowed, default=None):
    if not present(payload, key):
        return default
    return req_enum(payload, key, allowed)


def req_int(payload, key, lo=None, hi=None):
    if not present(payload, key):
        bad("%s is required." % key)
    value = payload[key]
    if isinstance(value, bool) or not isinstance(value, int):
        bad("%s must be an integer." % key)
    if lo is not None and value < lo:
        bad("%s may not be below %s." % (key, lo))
    if hi is not None and value > hi:
        bad("%s may not exceed %s." % (key, hi))
    return value


def opt_int(payload, key, lo=None, hi=None, default=None):
    if not present(payload, key):
        return default
    return req_int(payload, key, lo, hi)


def req_bool(payload, key):
    if not present(payload, key):
        bad("%s is required." % key)
    value = payload[key]
    if not isinstance(value, bool):
        bad("%s must be a boolean." % key)
    return value


def opt_bool(payload, key, default=None):
    if not present(payload, key):
        return default
    return req_bool(payload, key)


def _country(value, key):
    if len(value) != 2 or not value.isalpha() or value != value.upper():
        bad("%s must be exactly two upper-case letters." % key)
    return value


def req_country(payload, key):
    return _country(req_str(payload, key), key)


def opt_country(payload, key, default=None):
    if not present(payload, key):
        return default
    return req_country(payload, key)


def req_dt(payload, key):
    raw = req_str(payload, key)
    try:
        return raw, db.parse_dt(raw)
    except ValueError:
        bad("%s must be an ISO 8601 timestamp." % key)


def opt_dt(payload, key):
    if not present(payload, key):
        return None, None
    return req_dt(payload, key)


def req_str_list(payload, key, min_items=1, max_items=None, allowed=None,
                 distinct=True, item_min=1, item_max=None):
    if not present(payload, key):
        bad("%s is required." % key)
    return _str_list(payload[key], key, min_items, max_items, allowed, distinct,
                     item_min, item_max)


def opt_str_list(payload, key, min_items=0, max_items=None, allowed=None,
                 distinct=True, item_min=1, item_max=None, default=None):
    if not present(payload, key):
        return [] if default is None else default
    return _str_list(payload[key], key, min_items, max_items, allowed, distinct,
                     item_min, item_max)


def _str_list(value, key, min_items, max_items, allowed, distinct, item_min,
              item_max):
    if not isinstance(value, list):
        bad("%s must be an array." % key)
    for item in value:
        if not isinstance(item, str):
            bad("%s must contain only strings." % key)
        if len(item) < item_min:
            bad("%s entries may not be blank." % key)
        if item_max is not None and len(item) > item_max:
            bad("%s entries are too long." % key)
        if allowed is not None and item not in allowed:
            bad("%s contains an unrecognised value." % key)
    if len(value) < min_items:
        bad("%s must contain at least %d entries." % (key, min_items))
    if max_items is not None and len(value) > max_items:
        bad("%s may not contain more than %d entries." % (key, max_items))
    if distinct and len(set(value)) != len(value):
        bad("%s entries must be distinct." % key)
    return value


def pagination(args):
    """limit defaults to 10 (1..100); offset defaults to 0 and may not be negative."""
    limit = 10
    offset = 0
    raw_limit = args.get("limit")
    if raw_limit is not None and raw_limit != "":
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            bad("limit must be an integer.")
        if limit < 1:
            bad("limit must be at least 1.")
        if limit > 100:
            bad("limit may not exceed 100.")
    raw_offset = args.get("offset")
    if raw_offset is not None and raw_offset != "":
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            bad("offset must be an integer.")
        if offset < 0:
            bad("offset may not be negative.")
    return limit, offset


def query_enum(args, key, allowed):
    value = args.get(key)
    if value is None or value == "":
        return None
    if value not in allowed:
        bad("%s must be one of %s." % (key, ", ".join(sorted(allowed))))
    return value


def query_bool(args, key, default=None):
    value = args.get(key)
    if value is None or value == "":
        return default
    lowered = value.strip().lower()
    if lowered in ("true", "1"):
        return True
    if lowered in ("false", "0"):
        return False
    bad("%s must be a boolean." % key)
