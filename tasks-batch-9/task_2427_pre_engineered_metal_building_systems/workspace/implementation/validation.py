"""Request-shape validation -- precedence band 3 of PRD 2.5 (ERR_INVALID_REQUEST)."""

import re
from datetime import datetime, timezone

from flask import request

from errors import invalid


def body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise invalid("Request body must be a JSON object")
    return data


def present(data, key):
    return key in data and data[key] is not None


def _required_gate(data, key, required, default):
    """Return (should_continue, fallback)."""
    if present(data, key):
        return True, None
    if required:
        raise invalid("%s is required" % key)
    return False, default


def get_string(data, key, required=True, default=None, min_len=None, max_len=None, pattern=None):
    go, fallback = _required_gate(data, key, required, default)
    if not go:
        return fallback
    value = data[key]
    if not isinstance(value, str):
        raise invalid("%s must be a string" % key)
    if min_len is not None and len(value) < min_len:
        raise invalid("%s must be at least %d characters" % (key, min_len))
    if max_len is not None and len(value) > max_len:
        raise invalid("%s must be at most %d characters" % (key, max_len))
    if pattern is not None and re.fullmatch(pattern, value) is None:
        raise invalid("%s has an invalid format" % key)
    return value


def get_enum(data, key, allowed, required=True, default=None):
    go, fallback = _required_gate(data, key, required, default)
    if not go:
        return fallback
    value = data[key]
    if not isinstance(value, str) or value not in allowed:
        raise invalid("%s must be one of %s" % (key, ", ".join(allowed)))
    return value


def get_int(data, key, required=True, default=None, minimum=None, maximum=None, choices=None):
    go, fallback = _required_gate(data, key, required, default)
    if not go:
        return fallback
    value = data[key]
    if isinstance(value, bool):
        raise invalid("%s must be an integer" % key)
    if isinstance(value, int):
        result = value
    elif isinstance(value, float) and float(value).is_integer():
        result = int(value)
    else:
        raise invalid("%s must be an integer" % key)
    if minimum is not None and result < minimum:
        raise invalid("%s must be >= %s" % (key, minimum))
    if maximum is not None and result > maximum:
        raise invalid("%s must be <= %s" % (key, maximum))
    if choices is not None and result not in choices:
        raise invalid("%s must be one of %s" % (key, list(choices)))
    return result


def get_number(
    data,
    key,
    required=True,
    default=None,
    minimum=None,
    maximum=None,
    exclusive_minimum=None,
):
    go, fallback = _required_gate(data, key, required, default)
    if not go:
        return fallback
    value = data[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise invalid("%s must be a number" % key)
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            raise invalid("%s must be a finite number" % key)
    if minimum is not None and value < minimum:
        raise invalid("%s must be >= %s" % (key, minimum))
    if maximum is not None and value > maximum:
        raise invalid("%s must be <= %s" % (key, maximum))
    if exclusive_minimum is not None and value <= exclusive_minimum:
        raise invalid("%s must be > %s" % (key, exclusive_minimum))
    return value


def parse_datetime(value, key):
    if not isinstance(value, str) or not value.strip():
        raise invalid("%s must be an ISO 8601 datetime string" % key)
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        raise invalid("%s must be an ISO 8601 datetime string" % key)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def get_datetime(data, key, required=True):
    """Returns (aware datetime, original client string) or (None, None)."""
    go, _ = _required_gate(data, key, required, None)
    if not go:
        return None, None
    return parse_datetime(data[key], key), data[key]


def get_string_array(data, key, required=True):
    go, _ = _required_gate(data, key, required, None)
    if not go:
        return None
    value = data[key]
    if not isinstance(value, list) or len(value) == 0:
        raise invalid("%s must be a non-empty array of strings" % key)
    for entry in value:
        if not isinstance(entry, str) or entry == "":
            raise invalid("%s must contain only non-empty strings" % key)
    return value
