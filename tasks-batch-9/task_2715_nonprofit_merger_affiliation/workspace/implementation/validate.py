"""Request parsing and field validation — ladder rule 3 (ERR_INVALID_REQUEST).

Every helper raises ERR_INVALID_REQUEST (400) so that a single ladder position
covers body parsing, required fields, types, enum membership, integer ranges,
date/timestamp shapes and pagination bounds.
"""

import re

from flask import request

from clock import parse_date, parse_ts
from errors import fail

_MISSING = object()


def bad(message):
    fail("ERR_INVALID_REQUEST", message)


def body_object():
    """Parse the JSON body. An absent body is treated as an empty object."""
    raw = request.get_data(cache=True)
    if raw is None or len(raw.strip()) == 0:
        return {}
    data = request.get_json(silent=True, force=True)
    if data is None:
        bad("Request body is not valid JSON.")
    if not isinstance(data, dict):
        bad("Request body must be a JSON object.")
    return data


def _present(body, key):
    return key in body and body[key] is not None


def require_present(body, key):
    if key not in body or body[key] is None:
        bad("Field '%s' is required and must not be null." % key)


def req_str(body, key, min_len=None, max_len=None, pattern=None, non_blank=True):
    require_present(body, key)
    return _as_str(body[key], key, min_len, max_len, pattern, non_blank)


def opt_str(body, key, min_len=None, max_len=None, pattern=None, non_blank=True,
            default=None):
    if not _present(body, key):
        return default
    return _as_str(body[key], key, min_len, max_len, pattern, non_blank)


def _as_str(value, key, min_len, max_len, pattern, non_blank):
    if not isinstance(value, str):
        bad("Field '%s' must be a string." % key)
    if non_blank and value.strip() == "":
        bad("Field '%s' must not be blank." % key)
    if min_len is not None and len(value) < min_len:
        bad("Field '%s' must be at least %d characters." % (key, min_len))
    if max_len is not None and len(value) > max_len:
        bad("Field '%s' must be at most %d characters." % (key, max_len))
    if pattern is not None and not re.fullmatch(pattern, value):
        bad("Field '%s' does not match the required format." % key)
    return value


def req_int(body, key, minimum=None, maximum=None):
    require_present(body, key)
    return _as_int(body[key], key, minimum, maximum)


def opt_int(body, key, minimum=None, maximum=None, default=None):
    if not _present(body, key):
        return default
    return _as_int(body[key], key, minimum, maximum)


def _as_int(value, key, minimum, maximum):
    if isinstance(value, bool) or not isinstance(value, int):
        bad("Field '%s' must be an integer." % key)
    if minimum is not None and value < minimum:
        bad("Field '%s' must be at least %d." % (key, minimum))
    if maximum is not None and value > maximum:
        bad("Field '%s' must be at most %d." % (key, maximum))
    return value


def req_bool(body, key):
    require_present(body, key)
    return _as_bool(body[key], key)


def opt_bool(body, key, default=None):
    if not _present(body, key):
        return default
    return _as_bool(body[key], key)


def _as_bool(value, key):
    if not isinstance(value, bool):
        bad("Field '%s' must be a boolean." % key)
    return value


def req_enum(body, key, allowed):
    require_present(body, key)
    return _as_enum(body[key], key, allowed)


def opt_enum(body, key, allowed, default=None):
    if not _present(body, key):
        return default
    return _as_enum(body[key], key, allowed)


def _as_enum(value, key, allowed):
    if not isinstance(value, str):
        bad("Field '%s' must be a string." % key)
    if value not in allowed:
        bad("Field '%s' must be one of %s." % (key, ", ".join(allowed)))
    return value


def req_date(body, key):
    require_present(body, key)
    value = body[key]
    if not isinstance(value, str):
        bad("Field '%s' must be an ISO 8601 calendar date." % key)
    parsed = parse_date(value)
    if parsed is None:
        bad("Field '%s' must be an ISO 8601 calendar date (YYYY-MM-DD)." % key)
    return parsed


def req_ts(body, key):
    require_present(body, key)
    value = body[key]
    if not isinstance(value, str):
        bad("Field '%s' must be an ISO 8601 UTC timestamp." % key)
    parsed = parse_ts(value)
    if parsed is None:
        bad("Field '%s' must be an ISO 8601 UTC timestamp." % key)
    return parsed


def req_id(body, key):
    """A reference field: a non-blank string."""
    return req_str(body, key, min_len=1)


def opt_id(body, key):
    return opt_str(body, key, min_len=1)


# --------------------------------------------------------------- query string --

def pagination():
    limit = _query_int("limit", 10, 1, 100)
    offset = _query_int("offset", 0, 0, None)
    return limit, offset


def _query_int(name, default, minimum, maximum):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    if not re.fullmatch(r"[+-]?\d+", raw.strip()):
        bad("Query parameter '%s' must be an integer." % name)
    value = int(raw.strip())
    if minimum is not None and value < minimum:
        bad("Query parameter '%s' must be at least %d." % (name, minimum))
    if maximum is not None and value > maximum:
        bad("Query parameter '%s' must be at most %d." % (name, maximum))
    return value


def query_str(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    return raw


def query_enum(name, allowed):
    raw = query_str(name)
    if raw is None:
        return None
    if raw not in allowed:
        bad("Query parameter '%s' must be one of %s." % (name, ", ".join(allowed)))
    return raw


# ------------------------------------------------------------------- patterns --

EIN_PATTERN = r"^[0-9]{2}-[0-9]{7}$"
STATE_PATTERN = r"^[A-Z]{2}$"
CODE_PATTERN = r"^[A-Z]{2}-[A-Z_]+$"
CREW_PATTERN = r"^CREW-[A-Z0-9]{2,8}$"
