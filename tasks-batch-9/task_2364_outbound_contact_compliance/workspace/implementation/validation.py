"""Request well-formedness checks (PRD §2.8 step 4 -> ERR_INVALID_REQUEST)."""

import re

from flask import request

from errors import ApiError
from util import D, norm_dt, parse_date, parse_dt

PHONE_RE = re.compile(r"^\+[1-9][0-9]{7,14}$")
STATE_RE = re.compile(r"^[A-Z]{2}$")
HHMM_RE = re.compile(r"^([01][0-9]|2[0-3]):[0-5][0-9]$")

PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0


def bad(message):
    raise ApiError("ERR_INVALID_REQUEST", message)


def _present(body, name):
    return name in body and body[name] is not None


def require(body, name):
    if not _present(body, name):
        bad("Field '%s' is required." % name)
    return body[name]


def opt(body, name, default=None):
    if not _present(body, name):
        return default
    return body[name]


def req_str(body, name, allow_empty=True):
    value = require(body, name)
    if not isinstance(value, str):
        bad("Field '%s' must be a string." % name)
    if not allow_empty and not value.strip():
        bad("Field '%s' must be a non-empty string." % name)
    return value


def opt_str(body, name, default=None):
    if not _present(body, name):
        return default
    value = body[name]
    if not isinstance(value, str):
        bad("Field '%s' must be a string." % name)
    return value


def req_enum(body, name, allowed):
    value = require(body, name)
    if not isinstance(value, str) or value not in allowed:
        bad("Field '%s' must be one of %s." % (name, ", ".join(sorted(allowed))))
    return value


def opt_enum(body, name, allowed, default=None):
    if not _present(body, name):
        return default
    value = body[name]
    if not isinstance(value, str) or value not in allowed:
        bad("Field '%s' must be one of %s." % (name, ", ".join(sorted(allowed))))
    return value


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def req_int(body, name, minimum=None, maximum=None):
    value = require(body, name)
    if not _is_int(value):
        bad("Field '%s' must be an integer." % name)
    if minimum is not None and value < minimum:
        bad("Field '%s' must be >= %s." % (name, minimum))
    if maximum is not None and value > maximum:
        bad("Field '%s' must be <= %s." % (name, maximum))
    return value


def opt_int(body, name, default=None, minimum=None, maximum=None):
    if not _present(body, name):
        return default
    return req_int(body, name, minimum, maximum)


def req_bool(body, name):
    value = require(body, name)
    if not isinstance(value, bool):
        bad("Field '%s' must be a boolean." % name)
    return value


def opt_bool(body, name, default=None):
    if not _present(body, name):
        return default
    value = body[name]
    if not isinstance(value, bool):
        bad("Field '%s' must be a boolean." % name)
    return value


def req_decimal(body, name, minimum=None, maximum=None, places=2):
    value = require(body, name)
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        bad("Field '%s' must be a number." % name)
    try:
        dec = D(value)
    except Exception:
        bad("Field '%s' must be a number." % name)
    if dec != dec:  # NaN guard
        bad("Field '%s' must be a number." % name)
    if places is not None and -dec.as_tuple().exponent > places:
        bad("Field '%s' must carry at most %d decimal places." % (name, places))
    if minimum is not None and dec < D(minimum):
        bad("Field '%s' must be >= %s." % (name, minimum))
    if maximum is not None and dec > D(maximum):
        bad("Field '%s' must be <= %s." % (name, maximum))
    return dec


def opt_decimal(body, name, default=None, minimum=None, maximum=None, places=2):
    if not _present(body, name):
        return D(default) if default is not None else None
    return req_decimal(body, name, minimum, maximum, places)


def req_phone(body, name):
    value = req_str(body, name)
    if not PHONE_RE.match(value):
        bad("Field '%s' must be an E.164 phone number." % name)
    return value


def req_state(body, name):
    value = req_str(body, name)
    if not STATE_RE.match(value):
        bad("Field '%s' must be exactly two uppercase letters." % name)
    return value


def opt_state(body, name, default=None):
    if not _present(body, name):
        return default
    return req_state(body, name)


def req_hhmm(body, name):
    value = req_str(body, name)
    if not HHMM_RE.match(value):
        bad("Field '%s' must be HH:MM on a 24-hour clock." % name)
    return value


def req_datetime(body, name):
    value = require(body, name)
    normalised = norm_dt(value) if isinstance(value, str) else None
    if normalised is None:
        bad("Field '%s' must be an ISO 8601 timestamp." % name)
    return normalised


def req_date(body, name):
    value = require(body, name)
    if parse_date(value) is None:
        bad("Field '%s' must be a YYYY-MM-DD date." % name)
    return value


def req_str_list(body, name, min_len=1, allowed=None, unique=False, pattern=None):
    value = require(body, name)
    if not isinstance(value, list):
        bad("Field '%s' must be an array." % name)
    if len(value) < min_len:
        bad("Field '%s' must contain at least %d element(s)." % (name, min_len))
    for item in value:
        if not isinstance(item, str):
            bad("Field '%s' must contain strings only." % name)
        if allowed is not None and item not in allowed:
            bad("Field '%s' contains an unknown value." % name)
        if pattern is not None and not pattern.match(item):
            bad("Field '%s' contains a malformed value." % name)
    if unique and len(set(value)) != len(value):
        bad("Field '%s' must not contain duplicates." % name)
    return value


def opt_date_list(body, name, default=None):
    if not _present(body, name):
        return list(default) if default is not None else []
    value = body[name]
    if not isinstance(value, list):
        bad("Field '%s' must be an array." % name)
    for item in value:
        if parse_date(item) is None:
            bad("Field '%s' must contain YYYY-MM-DD dates." % name)
    return value


# --------------------------------------------------------------------------
# Query string helpers
# --------------------------------------------------------------------------


def pagination():
    limit = PAGINATION_DEFAULT_LIMIT
    offset = PAGINATION_DEFAULT_OFFSET
    raw_limit = request.args.get("limit")
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            bad("Query parameter 'limit' must be an integer.")
        if str(limit) != raw_limit.strip():
            bad("Query parameter 'limit' must be an integer.")
        if limit < PAGINATION_MIN_LIMIT or limit > PAGINATION_MAX_LIMIT:
            bad("Query parameter 'limit' must be between 1 and 100.")
    raw_offset = request.args.get("offset")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            bad("Query parameter 'offset' must be an integer.")
        if str(offset) != raw_offset.strip():
            bad("Query parameter 'offset' must be an integer.")
        if offset < 0:
            bad("Query parameter 'offset' must be >= 0.")
    return limit, offset


def query_enum(name, allowed):
    value = request.args.get(name)
    if value is None:
        return None
    if value not in allowed:
        bad("Query parameter '%s' must be one of %s." % (name, ", ".join(sorted(allowed))))
    return value


def query_str(name):
    return request.args.get(name)


def query_bool(name):
    value = request.args.get(name)
    if value is None:
        return None
    lowered = value.strip().lower()
    if lowered in ("true", "1"):
        return True
    if lowered in ("false", "0"):
        return False
    bad("Query parameter '%s' must be a boolean." % name)


def paginate(rows, limit, offset):
    total = len(rows)
    return rows[offset : offset + limit], total
