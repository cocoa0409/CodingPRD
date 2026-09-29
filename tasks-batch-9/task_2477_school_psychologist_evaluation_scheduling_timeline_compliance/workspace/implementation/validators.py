"""Request-body shape validation — validation ladder position 3.

Every failure here raises ERR_INVALID_REQUEST (422), which by the ladder of
PRD §2.11 is evaluated before any path identifier is resolved.
"""

import re

from flask import request

from errors import ApiError
from store import parse_date, parse_dt

BUILDING_CODE_RE = re.compile(r"^[A-Z0-9]{2,8}$")
LANG_RE = re.compile(r"^[a-z]{2}$")


def _bad(message):
    raise ApiError("ERR_INVALID_REQUEST", message)


def body():
    """The JSON request body as a dict; a missing/garbage body reads as empty."""
    raw = request.get_json(silent=True)
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        _bad("Request body must be a JSON object.")
    return raw


def has(data, key):
    return key in data and data[key] is not None


def _present(data, key):
    if not has(data, key):
        _bad("Field '%s' is required." % key)
    return data[key]


def req_str(data, key, allow_empty=False):
    value = _present(data, key)
    if not isinstance(value, str):
        _bad("Field '%s' must be a string." % key)
    if not allow_empty and value.strip() == "":
        _bad("Field '%s' must be a non-empty string." % key)
    return value


def opt_str(data, key, default=None, allow_empty=True):
    if not has(data, key):
        return default
    value = data[key]
    if not isinstance(value, str):
        _bad("Field '%s' must be a string." % key)
    if not allow_empty and value.strip() == "":
        _bad("Field '%s' must be a non-empty string." % key)
    return value


def req_enum(data, key, allowed):
    value = _present(data, key)
    if not isinstance(value, str) or value not in allowed:
        _bad("Field '%s' must be one of %s." % (key, ", ".join(sorted(allowed))))
    return value


def _check_int(key, value, minimum, maximum):
    if isinstance(value, bool) or not isinstance(value, int):
        _bad("Field '%s' must be an integer." % key)
    if minimum is not None and value < minimum:
        _bad("Field '%s' must be >= %d." % (key, minimum))
    if maximum is not None and value > maximum:
        _bad("Field '%s' must be <= %d." % (key, maximum))
    return value


def req_int(data, key, minimum=None, maximum=None):
    return _check_int(key, _present(data, key), minimum, maximum)


def opt_int(data, key, default, minimum=None, maximum=None):
    if not has(data, key):
        return default
    return _check_int(key, data[key], minimum, maximum)


def opt_bool(data, key, default):
    if not has(data, key):
        return default
    value = data[key]
    if not isinstance(value, bool):
        _bad("Field '%s' must be a boolean." % key)
    return value


def req_date(data, key):
    value = _present(data, key)
    parsed = parse_date(value)
    if parsed is None:
        _bad("Field '%s' must be a YYYY-MM-DD calendar date." % key)
    return parsed


def req_dt(data, key):
    value = _present(data, key)
    parsed = parse_dt(value)
    if parsed is None:
        _bad("Field '%s' must be an ISO 8601 datetime." % key)
    return parsed


def req_str_list(data, key, allow_empty_list=False):
    value = _present(data, key)
    if not isinstance(value, list):
        _bad("Field '%s' must be an array." % key)
    if not allow_empty_list and len(value) == 0:
        _bad("Field '%s' must be a non-empty array." % key)
    for item in value:
        if not isinstance(item, str) or item.strip() == "":
            _bad("Field '%s' must contain non-empty strings." % key)
    return list(value)


def opt_str_list(data, key, default, allow_empty_list=False):
    if not has(data, key):
        return list(default)
    return req_str_list(data, key, allow_empty_list=allow_empty_list)


def building_code(data, key):
    value = req_str(data, key)
    if not BUILDING_CODE_RE.match(value):
        _bad("Field '%s' must be 2-8 uppercase alphanumeric characters." % key)
    return value


def language_list(data, key, default):
    values = opt_str_list(data, key, default)
    for item in values:
        if not LANG_RE.match(item):
            _bad("Field '%s' must contain two-letter lowercase ISO 639-1 codes." % key)
    return values


DOMAINS = ("COGNITIVE", "ACADEMIC", "SOCIAL_EMOTIONAL", "ADAPTIVE")


def domain_list(data, key):
    values = req_str_list(data, key)
    seen = set()
    for item in values:
        if item not in DOMAINS:
            _bad("Field '%s' must be a subset of %s." % (key, ", ".join(DOMAINS)))
        if item in seen:
            _bad("Field '%s' must not contain duplicates." % key)
        seen.add(item)
    return values
