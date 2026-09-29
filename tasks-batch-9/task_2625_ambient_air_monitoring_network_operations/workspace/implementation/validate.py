"""Structural validation of request bodies and query parameters.

Everything in this module raises ERR_INVALID_REQUEST (400), which PRD section
2.11 places immediately after role authorisation and before any identifier
resolution.
"""
from datetime import datetime, timezone

from flask import request

from errors import ApiError

PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0


def bad(message):
    raise ApiError("ERR_INVALID_REQUEST", message)


def body():
    """Parsed JSON object body.  An absent/empty body is an empty object."""
    raw = request.get_data(cache=True)
    if raw is None or len(raw) == 0:
        return {}
    try:
        parsed = request.get_json(force=True, silent=False)
    except Exception:
        bad("Request body is not valid JSON.")
    if parsed is None:
        return {}
    if not isinstance(parsed, dict):
        bad("Request body must be a JSON object.")
    return parsed


def _present(data, name):
    return name in data and data[name] is not None


def req_present(data, name):
    if not _present(data, name):
        bad("Field '%s' is required." % name)


# --------------------------------------------------------------------------
# scalar readers
# --------------------------------------------------------------------------
def opt_string(data, name, default=None, min_len=None, max_len=None):
    if not _present(data, name):
        if name in data and data[name] is None:
            return None
        return default
    value = data[name]
    if not isinstance(value, str):
        bad("Field '%s' must be a string." % name)
    if min_len is not None and len(value) < min_len:
        bad("Field '%s' must be at least %d characters." % (name, min_len))
    if max_len is not None and len(value) > max_len:
        bad("Field '%s' must be at most %d characters." % (name, max_len))
    return value


def req_string(data, name, min_len=None, max_len=None):
    req_present(data, name)
    return opt_string(data, name, min_len=min_len, max_len=max_len)


def opt_int(data, name, default=None, lo=None, hi=None):
    if not _present(data, name):
        return default
    value = data[name]
    if isinstance(value, bool) or not isinstance(value, int):
        bad("Field '%s' must be an integer." % name)
    if lo is not None and value < lo:
        bad("Field '%s' must be >= %s." % (name, lo))
    if hi is not None and value > hi:
        bad("Field '%s' must be <= %s." % (name, hi))
    return value


def req_int(data, name, lo=None, hi=None):
    req_present(data, name)
    return opt_int(data, name, lo=lo, hi=hi)


def opt_number(data, name, default=None, lo=None, hi=None, exclusive_lo=None):
    if not _present(data, name):
        return default
    value = data[name]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        bad("Field '%s' must be a number." % name)
    value = float(value)
    if exclusive_lo is not None and not value > exclusive_lo:
        bad("Field '%s' must be > %s." % (name, exclusive_lo))
    if lo is not None and value < lo:
        bad("Field '%s' must be >= %s." % (name, lo))
    if hi is not None and value > hi:
        bad("Field '%s' must be <= %s." % (name, hi))
    return value


def req_number(data, name, lo=None, hi=None, exclusive_lo=None):
    req_present(data, name)
    return opt_number(data, name, lo=lo, hi=hi, exclusive_lo=exclusive_lo)


def opt_bool(data, name, default=None):
    if not _present(data, name):
        return default
    value = data[name]
    if not isinstance(value, bool):
        bad("Field '%s' must be a boolean." % name)
    return value


def req_bool(data, name):
    req_present(data, name)
    return opt_bool(data, name)


def opt_enum(data, name, allowed, default=None):
    if not _present(data, name):
        return default
    value = data[name]
    if not isinstance(value, str) or value not in allowed:
        bad("Field '%s' must be one of %s." % (name, ", ".join(sorted(allowed))))
    return value


def req_enum(data, name, allowed):
    req_present(data, name)
    return opt_enum(data, name, allowed)


def parse_datetime(value, name):
    if not isinstance(value, str):
        bad("Field '%s' must be an ISO 8601 datetime string." % name)
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except Exception:
        bad("Field '%s' must be an ISO 8601 datetime string." % name)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def opt_datetime(data, name, default=None):
    if not _present(data, name):
        return default
    return parse_datetime(data[name], name)


def req_datetime(data, name):
    req_present(data, name)
    return parse_datetime(data[name], name)


def req_list(data, name, min_len=1):
    req_present(data, name)
    value = data[name]
    if not isinstance(value, list):
        bad("Field '%s' must be an array." % name)
    if min_len is not None and len(value) < min_len:
        bad("Field '%s' must contain at least %d item(s)." % (name, min_len))
    for item in value:
        if not isinstance(item, dict):
            bad("Every item of '%s' must be an object." % name)
    return value


def req_id(data, name):
    """Foreign-key reference: must be a non-empty string."""
    req_present(data, name)
    value = data[name]
    if not isinstance(value, str) or value == "":
        bad("Field '%s' must be a non-empty string identifier." % name)
    return value


def opt_id(data, name):
    if not _present(data, name):
        return None
    value = data[name]
    if not isinstance(value, str) or value == "":
        bad("Field '%s' must be a non-empty string identifier." % name)
    return value


# --------------------------------------------------------------------------
# query parameters
# --------------------------------------------------------------------------
def pagination():
    args = request.args
    limit = PAGINATION_DEFAULT_LIMIT
    offset = PAGINATION_DEFAULT_OFFSET
    if "limit" in args:
        raw = args.get("limit")
        try:
            limit = int(raw)
        except (TypeError, ValueError):
            bad("Query parameter 'limit' must be an integer.")
        if str(raw).strip() != str(limit):
            bad("Query parameter 'limit' must be an integer.")
        if limit < PAGINATION_MIN_LIMIT or limit > PAGINATION_MAX_LIMIT:
            bad("Query parameter 'limit' must be between 1 and 100.")
    if "offset" in args:
        raw = args.get("offset")
        try:
            offset = int(raw)
        except (TypeError, ValueError):
            bad("Query parameter 'offset' must be an integer.")
        if str(raw).strip() != str(offset):
            bad("Query parameter 'offset' must be an integer.")
        if offset < 0:
            bad("Query parameter 'offset' may not be negative.")
    return limit, offset


def q_enum(name, allowed):
    value = request.args.get(name)
    if value is None:
        return None
    if value not in allowed:
        bad("Query parameter '%s' must be one of %s." % (name, ", ".join(sorted(allowed))))
    return value


def q_string(name):
    return request.args.get(name)


def q_int(name):
    value = request.args.get(name)
    if value is None:
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        bad("Query parameter '%s' must be an integer." % name)
    if value.strip() != str(parsed):
        bad("Query parameter '%s' must be an integer." % name)
    return parsed


def q_bool(name):
    value = request.args.get(name)
    if value is None:
        return None
    if value == "true":
        return True
    if value == "false":
        return False
    bad("Query parameter '%s' must be 'true' or 'false'." % name)
