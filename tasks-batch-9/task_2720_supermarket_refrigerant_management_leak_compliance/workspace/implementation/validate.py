"""Request-shape validation (validation priority 3 -> ERR_INVALID_REQUEST)."""
import json
from decimal import Decimal

from flask import request

import util
from errors import invalid

_MISSING = object()


def body():
    raw = request.get_data(as_text=True)
    if raw is None or raw.strip() == "":
        return {}
    try:
        parsed = json.loads(raw)
    except ValueError:
        raise invalid("request body is not valid JSON")
    if not isinstance(parsed, dict):
        raise invalid("request body must be a JSON object")
    return parsed


def _present(payload, field):
    value = payload.get(field, _MISSING)
    if value is _MISSING or value is None:
        return _MISSING
    return value


def req_str(payload, field, min_length=1):
    value = _present(payload, field)
    if value is _MISSING:
        raise invalid("%s is required" % field)
    if not isinstance(value, str):
        raise invalid("%s must be a string" % field)
    if len(value.strip()) < 1 or len(value) < min_length:
        raise invalid("%s must be at least %d characters" % (field, min_length))
    return value


def opt_str(payload, field, default=None):
    value = _present(payload, field)
    if value is _MISSING:
        return default
    if not isinstance(value, str):
        raise invalid("%s must be a string" % field)
    return value


def req_id(payload, field):
    value = _present(payload, field)
    if value is _MISSING:
        raise invalid("%s is required" % field)
    if not isinstance(value, str) or value.strip() == "":
        raise invalid("%s must be a string identifier" % field)
    return value


def opt_id(payload, field):
    value = _present(payload, field)
    if value is _MISSING:
        return None
    if not isinstance(value, str) or value.strip() == "":
        raise invalid("%s must be a string identifier" % field)
    return value


def req_enum(payload, field, allowed):
    value = _present(payload, field)
    if value is _MISSING:
        raise invalid("%s is required" % field)
    if not isinstance(value, str) or value not in allowed:
        raise invalid("%s must be one of %s" % (field, ", ".join(allowed)))
    return value


def opt_enum(payload, field, allowed, default=None):
    value = _present(payload, field)
    if value is _MISSING:
        return default
    if not isinstance(value, str) or value not in allowed:
        raise invalid("%s must be one of %s" % (field, ", ".join(allowed)))
    return value


def _as_int(field, value):
    if isinstance(value, bool) or not isinstance(value, int):
        raise invalid("%s must be an integer" % field)
    return value


def req_int(payload, field, minimum=None, maximum=None):
    value = _present(payload, field)
    if value is _MISSING:
        raise invalid("%s is required" % field)
    value = _as_int(field, value)
    _check_range(field, value, minimum, maximum)
    return value


def opt_int(payload, field, minimum=None, maximum=None, default=None):
    value = _present(payload, field)
    if value is _MISSING:
        return default
    value = _as_int(field, value)
    _check_range(field, value, minimum, maximum)
    return value


def _check_range(field, value, minimum, maximum):
    if minimum is not None and value < minimum:
        raise invalid("%s must be at least %s" % (field, minimum))
    if maximum is not None and value > maximum:
        raise invalid("%s must be at most %s" % (field, maximum))


def _as_decimal(field, value):
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        raise invalid("%s must be a number" % field)
    return util.dec(value)


def req_decimal(payload, field, minimum=None, maximum=None):
    value = _present(payload, field)
    if value is _MISSING:
        raise invalid("%s is required" % field)
    value = _as_decimal(field, value)
    _check_range(field, value, minimum, maximum)
    return value


def opt_decimal(payload, field, minimum=None, maximum=None, default=None):
    value = _present(payload, field)
    if value is _MISSING:
        return default
    value = _as_decimal(field, value)
    _check_range(field, value, minimum, maximum)
    return value


def req_bool(payload, field):
    value = _present(payload, field)
    if value is _MISSING:
        raise invalid("%s is required" % field)
    if not isinstance(value, bool):
        raise invalid("%s must be a boolean" % field)
    return value


def req_instant(payload, field):
    value = _present(payload, field)
    if value is _MISSING:
        raise invalid("%s is required" % field)
    parsed = util.parse_instant(value)
    if parsed is None:
        raise invalid("%s must be an ISO 8601 UTC instant" % field)
    return parsed


def opt_instant(payload, field, default=None):
    value = _present(payload, field)
    if value is _MISSING:
        return default
    parsed = util.parse_instant(value)
    if parsed is None:
        raise invalid("%s must be an ISO 8601 UTC instant" % field)
    return parsed


def opt_list(payload, field, default=None):
    value = _present(payload, field)
    if value is _MISSING:
        return list(default) if default is not None else []
    if not isinstance(value, list):
        raise invalid("%s must be an array" % field)
    return value
