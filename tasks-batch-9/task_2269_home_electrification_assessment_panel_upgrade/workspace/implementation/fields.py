"""Rung 3 of the validation ladder: request shape (ERR_INVALID_REQUEST, 400)."""
import re

import clock
import errors
from errors import ApiError

MISSING = object()


def _bad(message):
    raise ApiError(errors.ERR_INVALID_REQUEST, message=message)


def req_str(payload, key, allow_empty=False, pattern=None):
    if key not in payload:
        _bad("%s is required." % key)
    return _str_value(payload, key, payload[key], allow_empty, pattern)


def opt_str(payload, key, default=None, allow_empty=True, pattern=None):
    if key not in payload or payload[key] is None:
        return default
    return _str_value(payload, key, payload[key], allow_empty, pattern)


def _str_value(payload, key, value, allow_empty, pattern):
    if not isinstance(value, str):
        _bad("%s must be a string." % key)
    if not allow_empty and not value.strip():
        _bad("%s must not be empty." % key)
    if pattern is not None and not re.fullmatch(pattern, value):
        _bad("%s is malformed." % key)
    return value


def req_int(payload, key, minimum=None, maximum=None):
    if key not in payload:
        _bad("%s is required." % key)
    return _int_value(key, payload[key], minimum, maximum)


def opt_int(payload, key, default=None, minimum=None, maximum=None):
    if key not in payload or payload[key] is None:
        return default
    return _int_value(key, payload[key], minimum, maximum)


def _int_value(key, value, minimum, maximum):
    if isinstance(value, bool) or not isinstance(value, int):
        _bad("%s must be an integer." % key)
    if minimum is not None and value < minimum:
        _bad("%s must be at least %s." % (key, minimum))
    if maximum is not None and value > maximum:
        _bad("%s must be at most %s." % (key, maximum))
    return value


def req_num(payload, key, minimum=None, maximum=None):
    if key not in payload:
        _bad("%s is required." % key)
    return _num_value(key, payload[key], minimum, maximum)


def opt_num(payload, key, default=None, minimum=None, maximum=None):
    if key not in payload or payload[key] is None:
        return default
    return _num_value(key, payload[key], minimum, maximum)


def _num_value(key, value, minimum, maximum):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _bad("%s must be a number." % key)
    if minimum is not None and value < minimum:
        _bad("%s must be at least %s." % (key, minimum))
    if maximum is not None and value > maximum:
        _bad("%s must be at most %s." % (key, maximum))
    return value


def req_bool(payload, key):
    if key not in payload:
        _bad("%s is required." % key)
    return _bool_value(key, payload[key])


def opt_bool(payload, key, default=None):
    if key not in payload or payload[key] is None:
        return default
    return _bool_value(key, payload[key])


def _bool_value(key, value):
    if not isinstance(value, bool):
        _bad("%s must be a boolean." % key)
    return value


def req_enum(payload, key, choices):
    value = req_str(payload, key, allow_empty=False)
    if value not in choices:
        _bad("%s must be one of %s." % (key, ", ".join(choices)))
    return value


def opt_enum(payload, key, choices, default=None):
    if key not in payload or payload[key] is None:
        return default
    value = _str_value(payload, key, payload[key], False, None)
    if value not in choices:
        _bad("%s must be one of %s." % (key, ", ".join(choices)))
    return value


def req_date(payload, key):
    value = req_str(payload, key, allow_empty=False)
    parsed = clock.parse_date(value)
    if parsed is None:
        _bad("%s must be a YYYY-MM-DD date." % key)
    return value


def opt_date(payload, key, default=None):
    if key not in payload or payload[key] is None:
        return default
    value = _str_value(payload, key, payload[key], False, None)
    parsed = clock.parse_date(value)
    if parsed is None:
        _bad("%s must be a YYYY-MM-DD date." % key)
    return value


def req_datetime(payload, key):
    value = req_str(payload, key, allow_empty=False)
    parsed = clock.parse_datetime(value)
    if parsed is None:
        _bad("%s must be an ISO 8601 datetime." % key)
    return parsed


def req_list(payload, key):
    if key not in payload:
        _bad("%s is required." % key)
    value = payload[key]
    if not isinstance(value, list):
        _bad("%s must be an array." % key)
    return value


def opt_list(payload, key, default=None):
    if key not in payload or payload[key] is None:
        return default
    value = payload[key]
    if not isinstance(value, list):
        _bad("%s must be an array." % key)
    return value


def entry_object(value, label):
    if not isinstance(value, dict):
        _bad("Each entry of %s must be an object." % label)
    return value


def str_list(payload, key, default=None):
    value = opt_list(payload, key, default=None)
    if value is None:
        return default if default is not None else []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            _bad("%s must be an array of measure codes." % key)
    return value
