"""Structural validation helpers (precedence group 4 -> ERR_INVALID_REQUEST)."""

import re
from datetime import date, datetime, timezone

from flask import request

import errors
from errors import fail

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_COUNTRY_RE = re.compile(r"^[A-Z]{2}$")

MISSING = object()


def bad(message):
    fail(errors.ERR_INVALID_REQUEST, message)


def body():
    data = request.get_json(silent=True)
    if data is None:
        data = {}
    if not isinstance(data, dict):
        bad("Request body must be a JSON object")
    return data


def parse_date(value):
    if not isinstance(value, str) or not _DATE_RE.match(value):
        return None
    try:
        return date(int(value[0:4]), int(value[5:7]), int(value[8:10]))
    except ValueError:
        return None


def fmt_date(value):
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return "%04d-%02d-%02d" % (value.year, value.month, value.day)


def parse_instant(value):
    if not isinstance(value, str):
        return None
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# --- typed field readers ----------------------------------------------------

def req_str(data, key, min_len=1, max_len=None, pattern=None):
    if key not in data or data[key] is None:
        bad("Field '%s' is required" % key)
    value = data[key]
    if not isinstance(value, str):
        bad("Field '%s' must be a string" % key)
    if min_len is not None and len(value.strip()) < min_len:
        bad("Field '%s' must be at least %d characters" % (key, min_len))
    if max_len is not None and len(value) > max_len:
        bad("Field '%s' must be at most %d characters" % (key, max_len))
    if pattern is not None and not pattern.match(value):
        bad("Field '%s' has an invalid format" % key)
    return value


def opt_str(data, key, min_len=1, max_len=None, pattern=None, default=None):
    if key not in data or data[key] is None:
        return default
    return req_str(data, key, min_len=min_len, max_len=max_len, pattern=pattern)


def req_country(data, key):
    return req_str(data, key, min_len=2, max_len=2, pattern=_COUNTRY_RE)


def req_enum(data, key, allowed):
    value = req_str(data, key, min_len=1)
    if value not in allowed:
        bad("Field '%s' must be one of %s" % (key, ", ".join(sorted(allowed))))
    return value


def opt_enum(data, key, allowed, default=None):
    if key not in data or data[key] is None:
        return default
    return req_enum(data, key, allowed)


def req_int(data, key, minimum=None, maximum=None):
    if key not in data or data[key] is None:
        bad("Field '%s' is required" % key)
    value = data[key]
    if isinstance(value, bool) or not isinstance(value, int):
        bad("Field '%s' must be an integer" % key)
    if minimum is not None and value < minimum:
        bad("Field '%s' must be >= %d" % (key, minimum))
    if maximum is not None and value > maximum:
        bad("Field '%s' must be <= %d" % (key, maximum))
    return value


def opt_int(data, key, minimum=None, maximum=None, default=None):
    if key not in data or data[key] is None:
        return default
    return req_int(data, key, minimum=minimum, maximum=maximum)


def req_bool(data, key):
    if key not in data or data[key] is None:
        bad("Field '%s' is required" % key)
    value = data[key]
    if not isinstance(value, bool):
        bad("Field '%s' must be a boolean" % key)
    return value


def opt_bool(data, key, default=None):
    if key not in data or data[key] is None:
        return default
    return req_bool(data, key)


def req_date(data, key):
    if key not in data or data[key] is None:
        bad("Field '%s' is required" % key)
    parsed = parse_date(data[key])
    if parsed is None:
        bad("Field '%s' must be an ISO 8601 date (YYYY-MM-DD)" % key)
    return parsed


def opt_date(data, key, default=None):
    if key not in data or data[key] is None:
        return default
    return req_date(data, key)


def req_id(data, key):
    return req_str(data, key, min_len=1)


def opt_id(data, key):
    if key not in data or data[key] is None:
        return None
    return req_str(data, key, min_len=1)


def opt_str_array(data, key, allowed, default=None):
    if key not in data or data[key] is None:
        return list(default) if default is not None else []
    value = data[key]
    if not isinstance(value, list):
        bad("Field '%s' must be an array" % key)
    out = []
    for item in value:
        if not isinstance(item, str) or item not in allowed:
            bad("Field '%s' contains an invalid value" % key)
        if item not in out:
            out.append(item)
    return out


# --- query string -----------------------------------------------------------

def pagination():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit = 10
    offset = 0
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            bad("Query parameter 'limit' must be an integer")
        if limit < 1 or limit > 100:
            bad("Query parameter 'limit' must be between 1 and 100")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            bad("Query parameter 'offset' must be an integer")
        if offset < 0:
            bad("Query parameter 'offset' must be >= 0")
    return limit, offset


def query_enum(key, allowed):
    value = request.args.get(key)
    if value is None:
        return None
    if value not in allowed:
        bad("Query parameter '%s' must be one of %s" % (key, ", ".join(sorted(allowed))))
    return value


def query_str(key):
    value = request.args.get(key)
    if value is None:
        return None
    return value


def query_req_str(key, pattern=None):
    value = request.args.get(key)
    if value is None or value == "":
        bad("Query parameter '%s' is required" % key)
    if pattern is not None and not pattern.match(value):
        bad("Query parameter '%s' has an invalid format" % key)
    return value


def query_req_date(key):
    value = request.args.get(key)
    if value is None or value == "":
        bad("Query parameter '%s' is required" % key)
    parsed = parse_date(value)
    if parsed is None:
        bad("Query parameter '%s' must be an ISO 8601 date (YYYY-MM-DD)" % key)
    return parsed


COUNTRY_RE = _COUNTRY_RE
