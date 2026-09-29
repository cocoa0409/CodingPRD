"""Payload shape validation (rung 5 of the rejection ladder).

Every failure here is ERR_INVALID_REQUEST unless a caller asks for a
different error id (threshold ordering / interval well-formedness live in
their own rungs but are raised from the same helpers).
"""

from flask import request

from errors import ApiError

MISSING = object()


def payload():
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise ApiError("ERR_INVALID_REQUEST", "The request body must be a JSON object.")
    return body


def _bad(name, detail):
    raise ApiError("ERR_INVALID_REQUEST", "Field %s %s." % (name, detail))


def req_string(body, name):
    value = body.get(name, MISSING)
    if value is MISSING or value is None:
        _bad(name, "is required")
    if not isinstance(value, str) or not value.strip():
        _bad(name, "must be a non-empty string")
    return value


def opt_string(body, name, default=None):
    value = body.get(name, MISSING)
    if value is MISSING or value is None:
        return default
    if not isinstance(value, str):
        _bad(name, "must be a string")
    return value


def req_bool(body, name):
    value = body.get(name, MISSING)
    if value is MISSING or value is None:
        _bad(name, "is required")
    if not isinstance(value, bool):
        _bad(name, "must be a boolean")
    return value


def opt_bool(body, name, default=False):
    value = body.get(name, MISSING)
    if value is MISSING or value is None:
        return default
    if not isinstance(value, bool):
        _bad(name, "must be a boolean")
    return value


def _as_int(name, value):
    if isinstance(value, bool) or not isinstance(value, int):
        _bad(name, "must be an integer")
    return value


def req_int(body, name, minimum=None):
    value = body.get(name, MISSING)
    if value is MISSING or value is None:
        _bad(name, "is required")
    value = _as_int(name, value)
    if minimum is not None and value < minimum:
        _bad(name, "must be at least %d" % minimum)
    return value


def opt_int(body, name, default=None, minimum=None):
    value = body.get(name, MISSING)
    if value is MISSING or value is None:
        return default
    value = _as_int(name, value)
    if minimum is not None and value < minimum:
        _bad(name, "must be at least %d" % minimum)
    return value


def req_amount(body, name):
    """A *_cents input that must be a strictly positive integer."""
    return req_int(body, name, minimum=1)


def req_enum(body, name, allowed):
    value = req_string(body, name)
    if value not in allowed:
        _bad(name, "must be one of %s" % ", ".join(sorted(allowed)))
    return value


def opt_enum(body, name, allowed, default=None):
    value = body.get(name, MISSING)
    if value is MISSING or value is None:
        return default
    if not isinstance(value, str) or value not in allowed:
        _bad(name, "must be one of %s" % ", ".join(sorted(allowed)))
    return value


def req_id(body, name):
    """A foreign-key reference: shape checked here, existence at rung 4."""
    value = body.get(name, MISSING)
    if value is MISSING or value is None:
        _bad(name, "is required")
    if not isinstance(value, str) or not value.strip():
        _bad(name, "must be a non-empty string")
    return value


def opt_id(body, name):
    value = body.get(name, MISSING)
    if value is MISSING or value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        _bad(name, "must be a non-empty string")
    return value


def routing_number(body, name):
    value = req_string(body, name)
    text = value.strip()
    if len(text) != 9 or not text.isdigit():
        _bad(name, "must be exactly nine digits")
    return text
