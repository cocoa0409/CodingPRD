"""Request-body and query-parameter validation (PRD rungs 8 and 9)."""

from flask import request

import clock
from errors import fail

_MISSING = object()


def body():
    """The request body as a dict.  A non-object body is an invalid request."""
    raw = request.get_json(silent=True, force=True)
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        fail("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return raw


def _present(data, key):
    return key in data and data[key] is not None


def req_str(data, key, min_len=1, max_len=None):
    if not _present(data, key):
        fail("ERR_INVALID_REQUEST", "%s is required." % key)
    value = data[key]
    if not isinstance(value, str):
        fail("ERR_INVALID_REQUEST", "%s must be a string." % key)
    if not value.strip():
        fail("ERR_INVALID_REQUEST", "%s may not be blank." % key)
    if len(value) < min_len:
        fail("ERR_INVALID_REQUEST", "%s is too short." % key)
    if max_len is not None and len(value) > max_len:
        fail("ERR_INVALID_REQUEST", "%s is too long." % key)
    return value


def opt_str(data, key, min_len=1, max_len=None, default=None):
    if not _present(data, key):
        return default
    return req_str(data, key, min_len, max_len)


def req_enum(data, key, allowed):
    if not _present(data, key):
        fail("ERR_INVALID_REQUEST", "%s is required." % key)
    value = data[key]
    if not isinstance(value, str) or value not in allowed:
        fail("ERR_INVALID_REQUEST", "%s must be one of %s." % (key, ", ".join(sorted(allowed))))
    return value


def opt_enum(data, key, allowed, default=None):
    if not _present(data, key):
        return default
    return req_enum(data, key, allowed)


def _as_int(key, value):
    if isinstance(value, bool) or not isinstance(value, int):
        fail("ERR_INVALID_REQUEST", "%s must be an integer." % key)
    return value


def req_int(data, key, minimum=None, maximum=None):
    if not _present(data, key):
        fail("ERR_INVALID_REQUEST", "%s is required." % key)
    value = _as_int(key, data[key])
    if minimum is not None and value < minimum:
        fail("ERR_INVALID_REQUEST", "%s must be >= %s." % (key, minimum))
    if maximum is not None and value > maximum:
        fail("ERR_INVALID_REQUEST", "%s must be <= %s." % (key, maximum))
    return value


def opt_int(data, key, minimum=None, maximum=None, default=None):
    if not _present(data, key):
        return default
    return req_int(data, key, minimum, maximum)


def _as_num(key, value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        fail("ERR_INVALID_REQUEST", "%s must be a number." % key)
    return value


def req_num(data, key, minimum=None, maximum=None):
    if not _present(data, key):
        fail("ERR_INVALID_REQUEST", "%s is required." % key)
    value = _as_num(key, data[key])
    if minimum is not None and value < minimum:
        fail("ERR_INVALID_REQUEST", "%s must be >= %s." % (key, minimum))
    if maximum is not None and value > maximum:
        fail("ERR_INVALID_REQUEST", "%s must be <= %s." % (key, maximum))
    return value


def opt_num(data, key, minimum=None, maximum=None, default=None):
    if not _present(data, key):
        return default
    return req_num(data, key, minimum, maximum)


def req_bool(data, key):
    if not _present(data, key):
        fail("ERR_INVALID_REQUEST", "%s is required." % key)
    value = data[key]
    if not isinstance(value, bool):
        fail("ERR_INVALID_REQUEST", "%s must be a boolean." % key)
    return value


def opt_bool(data, key, default=None):
    if not _present(data, key):
        return default
    return req_bool(data, key)


def req_ts(data, key):
    if not _present(data, key):
        fail("ERR_INVALID_REQUEST", "%s is required." % key)
    parsed = clock.parse(data[key])
    if parsed is None:
        fail("ERR_INVALID_REQUEST", "%s must be an RFC3339 UTC timestamp." % key)
    return parsed


def opt_ts(data, key, default=None):
    if not _present(data, key):
        return default
    return req_ts(data, key)


def req_id(data, key):
    """A foreign-key identifier supplied in the body."""
    if not _present(data, key):
        fail("ERR_INVALID_REQUEST", "%s is required." % key)
    value = data[key]
    if not isinstance(value, str) or not value.strip():
        fail("ERR_INVALID_REQUEST", "%s must be a non-blank string." % key)
    return value


def pagination():
    """limit defaults to 10 (1..100); offset defaults to 0 (>= 0)."""
    limit = 10
    offset = 0
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is not None:
        limit = _int_param(raw_limit)
        if limit < 1 or limit > 100:
            fail("ERR_INVALID_PAGINATION")
    if raw_offset is not None:
        offset = _int_param(raw_offset)
        if offset < 0:
            fail("ERR_INVALID_PAGINATION")
    return limit, offset


def _int_param(raw):
    text = raw.strip()
    if not text:
        fail("ERR_INVALID_PAGINATION")
    negative = text.startswith("-")
    digits = text[1:] if negative or text.startswith("+") else text
    if not digits.isdigit():
        fail("ERR_INVALID_PAGINATION")
    value = int(text)
    return value


def filter_arg(name):
    value = request.args.get(name)
    if value is None:
        return None
    return value


def phase_volumes(data, key="phase_volumes"):
    """1..8 entries, keys the decimal strings 1..8, values integers 0..2000."""
    if not _present(data, key):
        fail("ERR_INVALID_REQUEST", "phase_volumes is required.")
    value = data[key]
    if not isinstance(value, dict) or not value:
        fail("ERR_INVALID_REQUEST", "phase_volumes must be a non-empty object.")
    if len(value) > 8:
        fail("ERR_INVALID_REQUEST", "phase_volumes may hold at most 8 entries.")
    cleaned = {}
    for raw_key, raw_value in value.items():
        if not isinstance(raw_key, str) or raw_key not in ("1", "2", "3", "4", "5", "6", "7", "8"):
            fail("ERR_INVALID_REQUEST", "phase_volumes keys must be the decimal strings 1..8.")
        if isinstance(raw_value, bool) or not isinstance(raw_value, int):
            fail("ERR_INVALID_REQUEST", "phase_volumes values must be integers.")
        if raw_value < 0 or raw_value > 2000:
            fail("ERR_INVALID_REQUEST", "phase_volumes values must lie in 0..2000.")
        cleaned[raw_key] = raw_value
    return cleaned
