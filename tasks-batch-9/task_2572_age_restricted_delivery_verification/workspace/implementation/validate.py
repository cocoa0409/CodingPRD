"""Tier 7 request-shape validation: required fields, JSON types, enum membership,
declared numeric ranges, parseable dates and timestamps. Everything here raises
ERR_VALIDATION with HTTP 400 (PRD 2.7).
"""
from decimal import Decimal

from flask import request

from errors import ApiError
from util import dec, is_int, is_number, parse_date, parse_dt


def _fail(message):
    raise ApiError("ERR_VALIDATION", message)


def body():
    raw = request.get_data(cache=True)
    if raw is None or raw.strip() == b"":
        return {}
    parsed = request.get_json(silent=True)
    if parsed is None or not isinstance(parsed, dict):
        _fail("request body must be a JSON object")
    return parsed


def present(data, name):
    return name in data and data[name] is not None


def req_str(data, name, max_len=None):
    value = data.get(name)
    if not isinstance(value, str) or value.strip() == "":
        _fail("%s is required and must be a non-empty string" % name)
    if max_len is not None and len(value) > max_len:
        _fail("%s exceeds the maximum length" % name)
    return value


def opt_str(data, name, default=None, max_len=None):
    if not present(data, name):
        return default
    return req_str(data, name, max_len)


def req_enum(data, name, allowed):
    value = data.get(name)
    if not isinstance(value, str) or value not in allowed:
        _fail("%s must be one of %s" % (name, ", ".join(allowed)))
    return value


def opt_enum(data, name, allowed, default=None):
    if not present(data, name):
        return default
    return req_enum(data, name, allowed)


def req_int(data, name, minimum=None, maximum=None):
    value = data.get(name)
    if not is_int(value):
        _fail("%s must be an integer" % name)
    if minimum is not None and value < minimum:
        _fail("%s must be at least %s" % (name, minimum))
    if maximum is not None and value > maximum:
        _fail("%s must not exceed %s" % (name, maximum))
    return value


def opt_int(data, name, minimum=None, maximum=None, default=None):
    if not present(data, name):
        return default
    return req_int(data, name, minimum, maximum)


def req_dec(data, name, minimum=None, maximum=None, exclusive_min=None):
    value = data.get(name)
    if not is_number(value):
        _fail("%s must be a number" % name)
    number = dec(value)
    if minimum is not None and number < dec(minimum):
        _fail("%s must be at least %s" % (name, minimum))
    if exclusive_min is not None and number <= dec(exclusive_min):
        _fail("%s must be greater than %s" % (name, exclusive_min))
    if maximum is not None and number > dec(maximum):
        _fail("%s must not exceed %s" % (name, maximum))
    return number


def req_bool(data, name):
    value = data.get(name)
    if not isinstance(value, bool):
        _fail("%s must be a boolean" % name)
    return value


def opt_bool(data, name, default=None):
    if not present(data, name):
        return default
    return req_bool(data, name)


def req_date(data, name):
    value = data.get(name)
    if not isinstance(value, str):
        _fail("%s must be a YYYY-MM-DD date string" % name)
    parsed = parse_date(value)
    if parsed is None:
        _fail("%s must be a YYYY-MM-DD date string" % name)
    return parsed


def opt_date(data, name):
    if not present(data, name):
        return None
    return req_date(data, name)


def req_dt(data, name):
    """Returns (datetime, original_string). Input timestamps are echoed verbatim."""
    value = data.get(name)
    if not isinstance(value, str):
        _fail("%s must be an ISO 8601 timestamp" % name)
    parsed = parse_dt(value)
    if parsed is None:
        _fail("%s must be an ISO 8601 timestamp" % name)
    return parsed, value


def opt_dt(data, name):
    if not present(data, name):
        return None, None
    return req_dt(data, name)


def req_str_list(data, name, min_len=None, max_len=None, allowed=None, item_max_len=None):
    value = data.get(name)
    if not isinstance(value, list):
        _fail("%s must be an array" % name)
    if min_len is not None and len(value) < min_len:
        _fail("%s must contain at least %d entries" % (name, min_len))
    if max_len is not None and len(value) > max_len:
        _fail("%s must contain at most %d entries" % (name, max_len))
    for item in value:
        if not isinstance(item, str) or item.strip() == "":
            _fail("every entry in %s must be a non-empty string" % name)
        if allowed is not None and item not in allowed:
            _fail("every entry in %s must be one of %s" % (name, ", ".join(allowed)))
        if item_max_len is not None and len(item) > item_max_len:
            _fail("an entry in %s exceeds the maximum length" % name)
    return list(value)


def opt_str_list(data, name, min_len=None, max_len=None, allowed=None, default=None):
    if not present(data, name):
        return list(default) if default is not None else None
    return req_str_list(data, name, min_len, max_len, allowed)


def req_signal_list(data, name, allowed_types):
    """`source_signals`: an array of {source_type, matched} objects."""
    value = data.get(name)
    if not isinstance(value, list):
        _fail("%s must be an array" % name)
    if len(value) < 1:
        _fail("%s must contain at least one signal" % name)
    out = []
    for item in value:
        if not isinstance(item, dict):
            _fail("every entry in %s must be an object" % name)
        source_type = item.get("source_type")
        matched = item.get("matched")
        if not isinstance(source_type, str) or source_type not in allowed_types:
            _fail("source_type must be one of %s" % ", ".join(allowed_types))
        if not isinstance(matched, bool):
            _fail("matched must be a boolean")
        out.append({"source_type": source_type, "matched": matched})
    return out


def enum_filter(name, allowed):
    """Validate an enum-valued query-string filter, returning None when absent."""
    raw = request.args.get(name)
    if raw is None:
        return None
    if raw not in allowed:
        _fail("%s must be one of %s" % (name, ", ".join(allowed)))
    return raw


def str_filter(name):
    raw = request.args.get(name)
    if raw is None or raw.strip() == "":
        return None
    return raw


def bool_filter(name):
    raw = request.args.get(name)
    if raw is None:
        return None
    lowered = raw.strip().lower()
    if lowered in ("true", "1"):
        return True
    if lowered in ("false", "0"):
        return False
    _fail("%s must be a boolean" % name)
