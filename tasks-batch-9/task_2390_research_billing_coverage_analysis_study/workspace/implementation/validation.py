"""Body-shape validation helpers (validation priority 3: ERR_INVALID_REQUEST)."""

import datetime as _dt
import re
from decimal import Decimal, InvalidOperation

from flask import request

from errors import ApiError

REGISTRY_RE = re.compile(r"^NCT[0-9]{8}$")
DATE_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")


def bad(message="The request body is invalid."):
    return ApiError("ERR_INVALID_REQUEST", message)


def body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise bad("Request body must be a JSON object.")
    return data


def req_str(data, key, min_len=1, max_len=None):
    if key not in data:
        raise bad("Missing required field: %s" % key)
    value = data[key]
    if not isinstance(value, str):
        raise bad("Field %s must be a string." % key)
    if len(value) < min_len:
        raise bad("Field %s must be at least %d characters." % (key, min_len))
    if max_len is not None and len(value) > max_len:
        raise bad("Field %s must be at most %d characters." % (key, max_len))
    return value


def opt_str(data, key, default=None, min_len=1, max_len=None):
    if key not in data or data[key] is None:
        return default
    return req_str(data, key, min_len=min_len, max_len=max_len)


def req_enum(data, key, allowed):
    value = req_str(data, key)
    if value not in allowed:
        raise bad("Field %s must be one of %s." % (key, ", ".join(sorted(allowed))))
    return value


def req_bool(data, key):
    if key not in data:
        raise bad("Missing required field: %s" % key)
    value = data[key]
    if not isinstance(value, bool):
        raise bad("Field %s must be a boolean." % key)
    return value


def req_int(data, key, minimum=None, maximum=None):
    if key not in data:
        raise bad("Missing required field: %s" % key)
    return _as_int(data[key], key, minimum, maximum)


def opt_int(data, key, default=None, minimum=None, maximum=None):
    if key not in data or data[key] is None:
        return default
    return _as_int(data[key], key, minimum, maximum)


def _as_int(value, key, minimum, maximum):
    if isinstance(value, bool) or not isinstance(value, int):
        raise bad("Field %s must be an integer." % key)
    if minimum is not None and value < minimum:
        raise bad("Field %s must be >= %d." % (key, minimum))
    if maximum is not None and value > maximum:
        raise bad("Field %s must be <= %d." % (key, maximum))
    return value


def req_rate(data, key):
    """A percentage: >= 0, <= 100, at most two decimal places."""
    if key not in data or data[key] is None:
        raise bad("Missing required field: %s" % key)
    value = data[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise bad("Field %s must be a number." % key)
    try:
        dec = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise bad("Field %s must be a number." % key)
    if dec < 0 or dec > 100:
        raise bad("Field %s must be between 0 and 100." % key)
    if -dec.as_tuple().exponent > 2:
        raise bad("Field %s may carry at most two decimal places." % key)
    return dec


def req_date(data, key):
    value = req_str(data, key)
    return parse_date(value, key)


def parse_date(value, key="date"):
    if not isinstance(value, str) or not DATE_RE.match(value):
        raise bad("Field %s must be a date in YYYY-MM-DD form." % key)
    try:
        _dt.date.fromisoformat(value)
    except ValueError:
        raise bad("Field %s must be a valid calendar date." % key)
    return value


def req_id(data, key):
    return req_str(data, key)


def opt_id(data, key):
    if key not in data or data[key] is None:
        return None
    return req_str(data, key)


def registry_number(data, key="registry_number"):
    """Returns (supplied, value).  A null value is accepted and means 'absent'."""
    if key not in data or data[key] is None:
        return False, None
    value = data[key]
    if not isinstance(value, str) or not REGISTRY_RE.match(value):
        raise bad("registry_number must match ^NCT[0-9]{8}$.")
    return True, value


def date_obj(value):
    return _dt.date.fromisoformat(value)


def shift_date(value, days):
    return (_dt.date.fromisoformat(value) + _dt.timedelta(days=days)).isoformat()


def days_between(start, end):
    return (_dt.date.fromisoformat(end) - _dt.date.fromisoformat(start)).days


def parse_iso8601(value, key="to_iso8601"):
    """Accepts an ISO 8601 instant, with or without fractional seconds, with a
    trailing Z or an explicit offset."""
    if not isinstance(value, str) or not value:
        raise bad("Field %s must be an ISO 8601 timestamp." % key)
    text = value.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        parsed = _dt.datetime.fromisoformat(text)
    except ValueError:
        raise bad("Field %s must be an ISO 8601 timestamp." % key)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=_dt.timezone.utc)
    return parsed.astimezone(_dt.timezone.utc)
