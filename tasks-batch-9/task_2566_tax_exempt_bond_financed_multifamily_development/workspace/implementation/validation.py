"""Payload well-formedness checks (PRD section 2.7 rule 4 -> ERR_INVALID_REQUEST).

Unknown keys are ignored rather than rejected.
"""

from flask import request

from errors import fail
from store import parse_iso


SENTINEL = object()


def body():
    """The parsed JSON body, or {} when absent/unparseable."""
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        return {}
    return data


def _present(data, key):
    return key in data and data[key] is not None


def require_present(data, key):
    if not _present(data, key):
        fail("ERR_INVALID_REQUEST", "Field '%s' is required." % key)
    return data[key]


def req_str(data, key, allow_empty=True):
    value = require_present(data, key)
    if not isinstance(value, str):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a string." % key)
    if not allow_empty and value.strip() == "":
        fail("ERR_INVALID_REQUEST", "Field '%s' must not be blank." % key)
    return value


def opt_str(data, key, default=None):
    if not _present(data, key):
        return default
    value = data[key]
    if not isinstance(value, str):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a string." % key)
    return value


def _int_check(value, key):
    if isinstance(value, bool) or not isinstance(value, int):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be an integer." % key)
    return value


def req_int(data, key, minimum=None, maximum=None):
    value = _int_check(require_present(data, key), key)
    _range(value, key, minimum, maximum)
    return value


def opt_int(data, key, minimum=None, maximum=None, default=None):
    if not _present(data, key):
        return default
    value = _int_check(data[key], key)
    _range(value, key, minimum, maximum)
    return value


def _range(value, key, minimum, maximum):
    if minimum is not None and value < minimum:
        fail("ERR_INVALID_REQUEST",
             "Field '%s' must be greater than or equal to %d." % (key, minimum))
    if maximum is not None and value > maximum:
        fail("ERR_INVALID_REQUEST",
             "Field '%s' must be less than or equal to %d." % (key, maximum))


def req_enum(data, key, allowed):
    value = require_present(data, key)
    if not isinstance(value, str) or value not in allowed:
        fail("ERR_INVALID_REQUEST",
             "Field '%s' must be one of %s." % (key, ", ".join(sorted(allowed))))
    return value


def opt_enum(data, key, allowed, default=None):
    if not _present(data, key):
        return default
    value = data[key]
    if not isinstance(value, str) or value not in allowed:
        fail("ERR_INVALID_REQUEST",
             "Field '%s' must be one of %s." % (key, ", ".join(sorted(allowed))))
    return value


def req_dt(data, key):
    """Returns (raw_string, datetime).  ISO-8601 with a Z suffix is mandatory."""
    value = require_present(data, key)
    if not isinstance(value, str):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be an ISO-8601 UTC timestamp." % key)
    parsed = parse_iso(value)
    if parsed is None:
        fail("ERR_INVALID_REQUEST",
             "Field '%s' must be an ISO-8601 timestamp with a Z suffix." % key)
    return value, parsed


def opt_dt(data, key):
    if not _present(data, key):
        return None, None
    return req_dt(data, key)


def req_id(data, key):
    """A foreign-key field: must be a present, non-null string."""
    value = require_present(data, key)
    if not isinstance(value, str) or value.strip() == "":
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a non-empty identifier." % key)
    return value
