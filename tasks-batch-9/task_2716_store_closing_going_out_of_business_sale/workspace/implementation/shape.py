"""Request shape validation (PRD 2.11 step 6) and query-string handling (PRD 2.3)."""

from decimal import Decimal, InvalidOperation

from flask import request

import clock
from errors import ApiError
from money import round4

PAGE_LIMIT_DEFAULT = 10
PAGE_LIMIT_MIN = 1
PAGE_LIMIT_MAX = 100
PAGE_OFFSET_DEFAULT = 0
PAGE_OFFSET_MIN = 0

_MISSING = object()


def bad(message="The request body or query string is malformed"):
    raise ApiError("ERR_INVALID_REQUEST", message)


def json_body():
    """Body must be a JSON object; an absent body is treated as an empty object."""
    data = request.get_data(cache=True, as_text=True)
    if data is None or data.strip() == "":
        return {}
    try:
        parsed = request.get_json(force=True, silent=False)
    except Exception:
        bad("Body is not valid JSON")
    if parsed is None:
        return {}
    if not isinstance(parsed, dict):
        bad("Body must be a JSON object")
    return parsed


def _fetch(body, key, required, default):
    if key not in body or body[key] is None:
        if required:
            bad("Field '%s' is required" % key)
        return _MISSING if default is _MISSING else default
    return body[key]


def field_str(body, key, required=True, default=None, allow_empty=False):
    value = _fetch(body, key, required, default)
    if key not in body or body[key] is None:
        return default
    if not isinstance(value, str):
        bad("Field '%s' must be a string" % key)
    if not allow_empty and value.strip() == "":
        bad("Field '%s' must not be empty" % key)
    return value


def field_enum(body, key, values, required=True, default=None):
    value = _fetch(body, key, required, default)
    if key not in body or body[key] is None:
        return default
    if not isinstance(value, str) or value not in values:
        bad("Field '%s' must be one of %s" % (key, sorted(values)))
    return value


def field_int(body, key, required=True, default=None, minimum=0, maximum=None):
    value = _fetch(body, key, required, default)
    if key not in body or body[key] is None:
        return default
    if isinstance(value, bool):
        bad("Field '%s' must be an integer" % key)
    if isinstance(value, float):
        if not value.is_integer():
            bad("Field '%s' must be an integer" % key)
        value = int(value)
    if not isinstance(value, int):
        bad("Field '%s' must be an integer" % key)
    if minimum is not None and value < minimum:
        bad("Field '%s' must be at least %s" % (key, minimum))
    if maximum is not None and value > maximum:
        bad("Field '%s' must be at most %s" % (key, maximum))
    return value


def field_pct(body, key, required=True, default=None, low="0", high="1"):
    value = _fetch(body, key, required, default)
    if key not in body or body[key] is None:
        return default
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        bad("Field '%s' must be a number" % key)
    try:
        number = Decimal(str(value))
    except InvalidOperation:
        bad("Field '%s' must be a number" % key)
    if number < Decimal(low) or number > Decimal(high):
        bad("Field '%s' must lie between %s and %s" % (key, low, high))
    return round4(number)


def field_bool(body, key, required=False, default=None):
    value = _fetch(body, key, required, default)
    if key not in body or body[key] is None:
        return default
    if not isinstance(value, bool):
        bad("Field '%s' must be a boolean" % key)
    return value


def field_date(body, key, required=True, default=None):
    value = _fetch(body, key, required, default)
    if key not in body or body[key] is None:
        return default
    if not isinstance(value, str):
        bad("Field '%s' must be an ISO-8601 date" % key)
    parsed = clock.parse_date(value)
    if parsed is None:
        bad("Field '%s' must be an ISO-8601 date (YYYY-MM-DD)" % key)
    return parsed


def field_instant(body, key, required=True, default=None):
    value = _fetch(body, key, required, default)
    if key not in body or body[key] is None:
        return default
    if not isinstance(value, str) or not value.strip().endswith("Z"):
        bad("Field '%s' must be an ISO-8601 UTC timestamp with a trailing Z" % key)
    parsed = clock.parse_instant(value)
    if parsed is None:
        bad("Field '%s' must be an ISO-8601 UTC timestamp" % key)
    return parsed


def field_code_list(body, key, values, required=True, default=None):
    value = _fetch(body, key, required, default)
    if key not in body or body[key] is None:
        return default
    if not isinstance(value, list):
        bad("Field '%s' must be an array" % key)
    for item in value:
        if not isinstance(item, str) or item not in values:
            bad("Field '%s' may only contain %s" % (key, sorted(values)))
    return list(value)


# ------------------------------------------------------------------- queries

def query_int(name, default, minimum=None, maximum=None):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        bad("Query parameter '%s' must be an integer" % name)
    if minimum is not None and value < minimum:
        bad("Query parameter '%s' is out of range" % name)
    if maximum is not None and value > maximum:
        bad("Query parameter '%s' is out of range" % name)
    return value


def pagination():
    limit = query_int("limit", PAGE_LIMIT_DEFAULT, PAGE_LIMIT_MIN, PAGE_LIMIT_MAX)
    offset = query_int("offset", PAGE_OFFSET_DEFAULT, PAGE_OFFSET_MIN, None)
    return limit, offset


def query_enum(name, values):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    if raw not in values:
        bad("Query parameter '%s' must be one of %s" % (name, sorted(values)))
    return raw


def query_str(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    return raw
