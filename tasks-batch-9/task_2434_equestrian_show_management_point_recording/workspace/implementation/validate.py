"""Request-body shape validation (ladder band 6 -> ERR_INVALID_REQUEST)."""

from flask import request

from core import parse_dt
from errors import ApiError


def _bad(msg):
    raise ApiError("ERR_INVALID_REQUEST", msg)


def body():
    if not request.data:
        return {}
    payload = request.get_json(silent=True)
    if payload is None:
        _bad("Request body must be a JSON object.")
    if not isinstance(payload, dict):
        _bad("Request body must be a JSON object.")
    return payload


def raw_body():
    """Body without shape enforcement, used for band-5 foreign-key extraction."""
    if not request.data:
        return {}
    payload = request.get_json(silent=True)
    return payload if isinstance(payload, dict) else {}


def fk_candidate(payload, key):
    """Return a string foreign key if present and string-typed, else None."""
    value = payload.get(key)
    return value if isinstance(value, str) else None


def req_str(payload, key, allow_empty=False):
    if key not in payload:
        _bad("Field '%s' is required." % key)
    value = payload[key]
    if not isinstance(value, str):
        _bad("Field '%s' must be a string." % key)
    if not allow_empty and not value.strip():
        _bad("Field '%s' must be a non-empty string." % key)
    return value


def opt_str(payload, key, default=None):
    if key not in payload or payload[key] is None:
        return default
    value = payload[key]
    if not isinstance(value, str):
        _bad("Field '%s' must be a string." % key)
    return value


def req_int(payload, key, minimum=None, maximum=None):
    if key not in payload:
        _bad("Field '%s' is required." % key)
    return _coerce_int(payload[key], key, minimum, maximum)


def opt_int(payload, key, default=None, minimum=None, maximum=None):
    if key not in payload or payload[key] is None:
        return default
    return _coerce_int(payload[key], key, minimum, maximum)


def _coerce_int(value, key, minimum, maximum):
    if isinstance(value, bool) or not isinstance(value, int):
        _bad("Field '%s' must be an integer." % key)
    if minimum is not None and value < minimum:
        _bad("Field '%s' is below its declared minimum." % key)
    if maximum is not None and value > maximum:
        _bad("Field '%s' is above its declared maximum." % key)
    return value


def req_number(payload, key, minimum=None):
    if key not in payload:
        _bad("Field '%s' is required." % key)
    return _coerce_number(payload[key], key, minimum)


def opt_number(payload, key, default=None, minimum=None):
    if key not in payload or payload[key] is None:
        return default
    return _coerce_number(payload[key], key, minimum)


def _coerce_number(value, key, minimum):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _bad("Field '%s' must be a number." % key)
    if minimum is not None and value < minimum:
        _bad("Field '%s' is below its declared minimum." % key)
    return value


def req_enum(payload, key, members):
    value = req_str(payload, key)
    if value not in members:
        _bad("Field '%s' must be one of: %s." % (key, ", ".join(members)))
    return value


def req_bool(payload, key):
    if key not in payload:
        _bad("Field '%s' is required." % key)
    value = payload[key]
    if not isinstance(value, bool):
        _bad("Field '%s' must be a boolean." % key)
    return value


def opt_bool(payload, key, default=False):
    if key not in payload or payload[key] is None:
        return default
    value = payload[key]
    if not isinstance(value, bool):
        _bad("Field '%s' must be a boolean." % key)
    return value


def req_dt(payload, key):
    if key not in payload:
        _bad("Field '%s' is required." % key)
    return parse_dt(payload[key])


def opt_dt(payload, key, default=None):
    if key not in payload or payload[key] is None:
        return default
    return parse_dt(payload[key])


def req_enum_array(payload, key, members):
    if key not in payload:
        _bad("Field '%s' is required." % key)
    value = payload[key]
    if not isinstance(value, list) or not value:
        _bad("Field '%s' must be a non-empty array." % key)
    for member in value:
        if not isinstance(member, str) or member not in members:
            _bad("Field '%s' members must be drawn from: %s." % (key, ", ".join(members)))
    return list(value)
