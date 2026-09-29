"""Schema validation (validation ladder step 3 -> ERR_INVALID_REQUEST)."""

import re
from datetime import date, datetime, timezone

from flask import request

from errors import api_error

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_TS_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt](\d{2}):(\d{2}):(\d{2})(\.\d{1,6})?(Z|z|\+00:?00|-00:?00)$"
)
_STATE_CODE_RE = re.compile(r"^[A-Z]{2}$")


def bad(msg):
    return api_error("ERR_INVALID_REQUEST", msg)


def body(required=True):
    """Parse the JSON request body.  Absent body is treated as {}."""
    raw = request.get_data(cache=True, as_text=True)
    if raw is None or raw.strip() == "":
        if required:
            return {}
        return {}
    try:
        parsed = request.get_json(force=True, silent=False)
    except Exception:
        raise bad("Request body is not valid JSON.")
    if parsed is None:
        return {}
    if not isinstance(parsed, dict):
        raise bad("Request body must be a JSON object.")
    return parsed


def present(data, key):
    return key in data and data[key] is not None


def require(data, key):
    if key not in data or data[key] is None:
        raise bad("Field '%s' is required." % key)
    return data[key]


# --------------------------------------------------------------- strings ---
def req_str(data, key, min_len=1, max_len=None, pattern=None):
    value = require(data, key)
    return _check_str(value, key, min_len, max_len, pattern)


def opt_str(data, key, min_len=1, max_len=None, pattern=None, default=None):
    if not present(data, key):
        return default
    return _check_str(data[key], key, min_len, max_len, pattern)


def _check_str(value, key, min_len, max_len, pattern):
    if not isinstance(value, str):
        raise bad("Field '%s' must be a string." % key)
    if min_len is not None and len(value.strip()) < min_len:
        raise bad("Field '%s' must be at least %d characters." % (key, min_len))
    if max_len is not None and len(value) > max_len:
        raise bad("Field '%s' must be at most %d characters." % (key, max_len))
    if pattern is not None and not pattern.match(value):
        raise bad("Field '%s' is malformed." % key)
    return value


def req_state_code(data, key):
    return req_str(data, key, 2, 2, _STATE_CODE_RE)


# ----------------------------------------------------------------- enums ---
def req_enum(data, key, allowed):
    value = require(data, key)
    return _check_enum(value, key, allowed)


def opt_enum(data, key, allowed, default=None):
    if not present(data, key):
        return default
    return _check_enum(data[key], key, allowed)


def _check_enum(value, key, allowed):
    if not isinstance(value, str) or value not in allowed:
        raise bad("Field '%s' must be one of %s." % (key, ", ".join(allowed)))
    return value


def req_enum_array(data, key, allowed, default=None):
    if not present(data, key):
        return list(default) if default is not None else []
    value = data[key]
    if not isinstance(value, list):
        raise bad("Field '%s' must be an array." % key)
    out = []
    for item in value:
        if not isinstance(item, str) or item not in allowed:
            raise bad("Field '%s' contains a value outside its domain." % key)
        if item in out:
            raise bad("Field '%s' must contain distinct values." % key)
        out.append(item)
    return out


# --------------------------------------------------------------- numbers ---
def req_int(data, key, minimum=None, maximum=None):
    value = require(data, key)
    return _check_int(value, key, minimum, maximum)


def opt_int(data, key, minimum=None, maximum=None, default=None):
    if not present(data, key):
        return default
    return _check_int(data[key], key, minimum, maximum)


def _check_int(value, key, minimum, maximum):
    if isinstance(value, bool) or not isinstance(value, int):
        raise bad("Field '%s' must be an integer." % key)
    if minimum is not None and value < minimum:
        raise bad("Field '%s' must be at least %s." % (key, minimum))
    if maximum is not None and value > maximum:
        raise bad("Field '%s' must be at most %s." % (key, maximum))
    return value


def opt_number(data, key, minimum=None, default=None):
    if not present(data, key):
        return default
    value = data[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise bad("Field '%s' must be a number." % key)
    if minimum is not None and value < minimum:
        raise bad("Field '%s' must be at least %s." % (key, minimum))
    return value


def opt_bool(data, key, default=None):
    if not present(data, key):
        return default
    value = data[key]
    if not isinstance(value, bool):
        raise bad("Field '%s' must be a boolean." % key)
    return value


# ----------------------------------------------------------------- dates ---
def req_date(data, key):
    value = require(data, key)
    return _check_date(value, key)


def opt_date(data, key, default=None):
    if not present(data, key):
        return default
    return _check_date(data[key], key)


def _check_date(value, key):
    if not isinstance(value, str) or not _DATE_RE.match(value):
        raise bad("Field '%s' must be an ISO 8601 calendar date (YYYY-MM-DD)." % key)
    try:
        return date(int(value[0:4]), int(value[5:7]), int(value[8:10]))
    except ValueError:
        raise bad("Field '%s' is not a real calendar date." % key)


def req_datetime(data, key):
    value = require(data, key)
    return parse_timestamp(value, key)


def parse_timestamp(value, key):
    if not isinstance(value, str):
        raise bad("Field '%s' must be an ISO 8601 UTC timestamp." % key)
    m = _TS_RE.match(value.strip())
    if not m:
        raise bad("Field '%s' must be an ISO 8601 UTC timestamp." % key)
    frac = m.group(7) or ".0"
    micro = int(round(float(frac) * 1000000))
    try:
        return datetime(
            int(m.group(1)),
            int(m.group(2)),
            int(m.group(3)),
            int(m.group(4)),
            int(m.group(5)),
            int(m.group(6)),
            micro,
            tzinfo=timezone.utc,
        )
    except ValueError:
        raise bad("Field '%s' is not a real instant." % key)


# ------------------------------------------------------- query parameters ---
def pagination():
    limit = 10
    offset = 0
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is not None:
        limit = _query_int("limit", raw_limit)
        if limit < 1 or limit > 100:
            raise bad("Query parameter 'limit' must be between 1 and 100.")
    if raw_offset is not None:
        offset = _query_int("offset", raw_offset)
        if offset < 0:
            raise bad("Query parameter 'offset' must not be negative.")
    return limit, offset


def _query_int(name, raw):
    try:
        return int(raw)
    except (TypeError, ValueError):
        raise bad("Query parameter '%s' must be an integer." % name)


def q_str(name):
    return request.args.get(name)


def q_int(name):
    raw = request.args.get(name)
    if raw is None:
        return None
    return _query_int(name, raw)


def q_enum(name, allowed):
    raw = request.args.get(name)
    if raw is None:
        return None
    if raw not in allowed:
        raise bad("Query parameter '%s' must be one of %s." % (name, ", ".join(allowed)))
    return raw


def q_bool(name):
    raw = request.args.get(name)
    if raw is None:
        return None
    lowered = raw.strip().lower()
    if lowered in ("true", "1"):
        return True
    if lowered in ("false", "0"):
        return False
    raise bad("Query parameter '%s' must be a boolean." % name)
