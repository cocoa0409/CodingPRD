"""Structural validation (PRD section 2.6 rank 12) - every failure is ERR_INVALID_REQUEST."""

import re

from flask import request

from db import parse_date, parse_dt
from errors import api_error

MISSING = object()

UPPER_CODE_RE = re.compile(r"^[A-Z0-9-]+$")
HEX_RE = re.compile(r"^[0-9a-fA-F]+$")


def payload():
    """Return the request body as a dict; an absent body is an empty dict."""
    raw = request.get_data(cache=True)
    if raw is None or len(raw.strip()) == 0:
        return {}
    data = request.get_json(silent=True, force=True)
    if not isinstance(data, dict):
        api_error("ERR_INVALID_REQUEST", "request body must be a JSON object")
    return data


def has_key(body, name):
    return name in body


def has_value(body, name):
    return name in body and body[name] is not None


def _bad(name, detail):
    api_error("ERR_INVALID_REQUEST", "%s %s" % (name, detail))


def _get(body, name):
    if name not in body:
        return MISSING
    return body[name]


def _require_present(body, name):
    value = _get(body, name)
    if value is MISSING or value is None:
        _bad(name, "is required")
    return value


def check_int(name, value, minimum=None, maximum=None):
    if isinstance(value, bool) or not isinstance(value, int):
        _bad(name, "must be an integer")
    if minimum is not None and value < minimum:
        _bad(name, "must be >= %d" % minimum)
    if maximum is not None and value > maximum:
        _bad(name, "must be <= %d" % maximum)
    return value


def req_int(body, name, minimum=None, maximum=None):
    return check_int(name, _require_present(body, name), minimum, maximum)


def opt_int(body, name, default=None, minimum=None, maximum=None):
    value = _get(body, name)
    if value is MISSING or value is None:
        return default
    return check_int(name, value, minimum, maximum)


def check_number(name, value, minimum=None, exclusive_minimum=None, maximum=None):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _bad(name, "must be a number")
    if minimum is not None and value < minimum:
        _bad(name, "must be >= %s" % minimum)
    if exclusive_minimum is not None and value <= exclusive_minimum:
        _bad(name, "must be > %s" % exclusive_minimum)
    if maximum is not None and value > maximum:
        _bad(name, "must be <= %s" % maximum)
    return value


def opt_number(body, name, default=None, minimum=None, exclusive_minimum=None, maximum=None):
    value = _get(body, name)
    if value is MISSING or value is None:
        return default
    return check_number(name, value, minimum, exclusive_minimum, maximum)


def check_str(name, value, min_len=None, max_len=None, pattern=None):
    if not isinstance(value, str):
        _bad(name, "must be a string")
    if min_len is not None and len(value) < min_len:
        _bad(name, "must be at least %d characters" % min_len)
    if max_len is not None and len(value) > max_len:
        _bad(name, "must be at most %d characters" % max_len)
    if pattern is not None and not pattern.match(value):
        _bad(name, "has an invalid format")
    return value


def req_str(body, name, min_len=None, max_len=None, pattern=None):
    return check_str(name, _require_present(body, name), min_len, max_len, pattern)


def opt_str(body, name, default=None, min_len=None, max_len=None, pattern=None):
    value = _get(body, name)
    if value is MISSING or value is None:
        return default
    return check_str(name, value, min_len, max_len, pattern)


def check_enum(name, value, allowed):
    if not isinstance(value, str) or value not in allowed:
        _bad(name, "must be one of %s" % ", ".join(sorted(allowed)))
    return value


def req_enum(body, name, allowed):
    return check_enum(name, _require_present(body, name), allowed)


def opt_enum(body, name, allowed, default=None):
    value = _get(body, name)
    if value is MISSING or value is None:
        return default
    return check_enum(name, value, allowed)


def req_datetime(body, name):
    value = _require_present(body, name)
    if not isinstance(value, str):
        _bad(name, "must be an ISO 8601 timestamp string")
    parsed = parse_dt(value)
    if parsed is None:
        _bad(name, "must be a valid ISO 8601 timestamp")
    return parsed


def opt_datetime(body, name, default=None):
    value = _get(body, name)
    if value is MISSING or value is None:
        return default
    return req_datetime(body, name)


def req_date(body, name):
    value = _require_present(body, name)
    if not isinstance(value, str):
        _bad(name, "must be a YYYY-MM-DD date string")
    parsed = parse_date(value)
    if parsed is None:
        _bad(name, "must be a valid YYYY-MM-DD date")
    return parsed


def opt_date(body, name, default=None):
    value = _get(body, name)
    if value is MISSING or value is None:
        return default
    return req_date(body, name)


def filter_enum(args, name, allowed):
    """Validate an enum-valued query filter."""
    if name not in args:
        return None
    value = args.get(name)
    if value is None or value == "":
        return None
    return check_enum(name, value, allowed)


def filter_str(args, name):
    if name not in args:
        return None
    value = args.get(name)
    if value is None or value == "":
        return None
    return value


def filter_int(args, name, minimum=None):
    if name not in args:
        return None
    raw = args.get(name)
    if raw is None or raw == "":
        return None
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        _bad(name, "must be an integer")
    if minimum is not None and value < minimum:
        _bad(name, "must be >= %d" % minimum)
    return value
