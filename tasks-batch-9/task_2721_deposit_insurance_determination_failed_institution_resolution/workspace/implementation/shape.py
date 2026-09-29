"""Request-shape validation -- stage 4 of the pipeline in PRD section 2.11.

Every failure here is ``ERR_INVALID_REQUEST`` with HTTP 400.  Note the pipeline
order: existence of every named resource (stage 3) is resolved *before* shape,
so a caller that supplies an unknown foreign key together with a malformed body
sees the 404, not the 400.
"""

import re

from flask import request

from errors import ApiError
from util import parse_iso

DIGITS_4_6 = re.compile(r"^[0-9]{4,6}$")
TWO_UPPER = re.compile(r"^[A-Z]{2}$")


def _bad(message):
    raise ApiError("ERR_INVALID_REQUEST", message)


def raw_body():
    """The parsed JSON body as a dict, or ``{}`` when there is no usable body.

    Returned leniently so that stage-3 existence checks can read foreign keys
    out of it; stage 4 (:func:`body`) is what rejects a malformed payload.
    """
    try:
        parsed = request.get_json(silent=True, force=True)
    except Exception:  # pragma: no cover - defensive
        parsed = None
    return parsed if isinstance(parsed, dict) else {}


def body():
    """The parsed JSON body, rejecting anything that is not a JSON object."""
    try:
        parsed = request.get_json(silent=True, force=True)
    except Exception:  # pragma: no cover - defensive
        parsed = None
    if parsed is None:
        if request.get_data(cache=True):
            _bad("Request body must be a JSON object")
        return {}
    if not isinstance(parsed, dict):
        _bad("Request body must be a JSON object")
    return parsed


def present(payload, key):
    return key in payload and payload[key] is not None


def req_int(payload, key, minimum=None, maximum=None):
    if not present(payload, key):
        _bad("Missing required field %s" % key)
    value = payload[key]
    if isinstance(value, bool) or not isinstance(value, int):
        _bad("%s must be an integer" % key)
    if minimum is not None and value < minimum:
        _bad("%s is below its minimum" % key)
    if maximum is not None and value > maximum:
        _bad("%s exceeds its maximum" % key)
    return value


def opt_int(payload, key, default=None, minimum=None, maximum=None):
    if not present(payload, key):
        return default
    return req_int(payload, key, minimum, maximum)


def req_str(payload, key, min_len=1, max_len=None, pattern=None, contains=None):
    if not present(payload, key):
        _bad("Missing required field %s" % key)
    value = payload[key]
    if not isinstance(value, str):
        _bad("%s must be a string" % key)
    if min_len is not None and len(value) < min_len:
        _bad("%s is shorter than its minimum length" % key)
    if max_len is not None and len(value) > max_len:
        _bad("%s exceeds its maximum length" % key)
    if pattern is not None and not pattern.match(value):
        _bad("%s is malformed" % key)
    if contains is not None and contains not in value:
        _bad("%s is malformed" % key)
    return value


def opt_str(payload, key, default=None, min_len=1, max_len=None, pattern=None):
    if not present(payload, key):
        return default
    return req_str(payload, key, min_len, max_len, pattern)


def req_enum(payload, key, allowed):
    if not present(payload, key):
        _bad("Missing required field %s" % key)
    value = payload[key]
    if not isinstance(value, str) or value not in allowed:
        _bad("%s is not a recognized enum member" % key)
    return value


def opt_enum(payload, key, allowed, default=None):
    if not present(payload, key):
        return default
    return req_enum(payload, key, allowed)


def req_datetime(payload, key):
    if not present(payload, key):
        _bad("Missing required field %s" % key)
    value = payload[key]
    parsed = parse_iso(value) if isinstance(value, str) else None
    if parsed is None:
        _bad("%s must be an ISO 8601 instant" % key)
    return parsed


def opt_datetime(payload, key, default=None):
    if not present(payload, key):
        return default
    return req_datetime(payload, key)


def req_id(payload, key):
    """A foreign-key string field.  Existence is checked separately at stage 3."""
    if not present(payload, key):
        _bad("Missing required field %s" % key)
    value = payload[key]
    if not isinstance(value, str) or not value:
        _bad("%s must be a string" % key)
    return value


def forbid(payload, key, reason):
    if present(payload, key):
        _bad(reason)
