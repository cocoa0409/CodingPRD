"""Request-shape validation (PRD 2.7 rank 4 -> ERR_INVALID_REQUEST)."""
import re
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation

from errors import fail

_MISSING = object()
STATE_CODE_RE = re.compile(r"^[A-Z]{2}$")


def _bad(msg):
    fail("ERR_INVALID_REQUEST", msg)


def req_str(body, key, allow_empty=False):
    value = body.get(key, _MISSING)
    if value is _MISSING or value is None:
        _bad("%s is required." % key)
    if not isinstance(value, str):
        _bad("%s must be a string." % key)
    if not allow_empty and value.strip() == "":
        _bad("%s may not be empty." % key)
    return value


def opt_str(body, key, default=None, allow_empty=True):
    value = body.get(key, _MISSING)
    if value is _MISSING or value is None:
        return default
    if not isinstance(value, str):
        _bad("%s must be a string." % key)
    if not allow_empty and value.strip() == "":
        _bad("%s may not be empty." % key)
    return value


def _check_int(key, value, minimum, maximum):
    if isinstance(value, bool) or not isinstance(value, int):
        _bad("%s must be an integer." % key)
    if minimum is not None and value < minimum:
        _bad("%s must be >= %s." % (key, minimum))
    if maximum is not None and value > maximum:
        _bad("%s must be <= %s." % (key, maximum))
    return value


def req_int(body, key, minimum=None, maximum=None):
    value = body.get(key, _MISSING)
    if value is _MISSING or value is None:
        _bad("%s is required." % key)
    return _check_int(key, value, minimum, maximum)


def opt_int(body, key, default=None, minimum=None, maximum=None):
    value = body.get(key, _MISSING)
    if value is _MISSING or value is None:
        return default
    return _check_int(key, value, minimum, maximum)


def _check_num(key, value, minimum, maximum):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _bad("%s must be a number." % key)
    if minimum is not None and value < minimum:
        _bad("%s must be >= %s." % (key, minimum))
    if maximum is not None and value > maximum:
        _bad("%s must be <= %s." % (key, maximum))
    return value


def req_num(body, key, minimum=None, maximum=None):
    value = body.get(key, _MISSING)
    if value is _MISSING or value is None:
        _bad("%s is required." % key)
    return _check_num(key, value, minimum, maximum)


def opt_num(body, key, default=None, minimum=None, maximum=None):
    value = body.get(key, _MISSING)
    if value is _MISSING or value is None:
        return default
    return _check_num(key, value, minimum, maximum)


def req_bool(body, key):
    value = body.get(key, _MISSING)
    if value is _MISSING or value is None:
        _bad("%s is required." % key)
    if not isinstance(value, bool):
        _bad("%s must be a boolean." % key)
    return value


def opt_bool(body, key, default=None):
    value = body.get(key, _MISSING)
    if value is _MISSING or value is None:
        return default
    if not isinstance(value, bool):
        _bad("%s must be a boolean." % key)
    return value


def req_enum(body, key, allowed):
    value = req_str(body, key)
    if value not in allowed:
        _bad("%s must be one of %s." % (key, ", ".join(allowed)))
    return value


def opt_enum(body, key, allowed, default=None):
    value = opt_str(body, key)
    if value is None:
        return default
    if value not in allowed:
        _bad("%s must be one of %s." % (key, ", ".join(allowed)))
    return value


def req_state_code(body, key):
    value = req_str(body, key)
    if not STATE_CODE_RE.match(value):
        _bad("%s must be exactly two uppercase letters." % key)
    return value


def opt_state_code(body, key, default=None):
    value = opt_str(body, key)
    if value is None:
        return default
    if not STATE_CODE_RE.match(value):
        _bad("%s must be exactly two uppercase letters." % key)
    return value


def req_obj(body, key):
    value = body.get(key, _MISSING)
    if value is _MISSING or value is None:
        _bad("%s is required." % key)
    if not isinstance(value, dict):
        _bad("%s must be an object." % key)
    return value


def opt_obj(body, key, default=None):
    value = body.get(key, _MISSING)
    if value is _MISSING or value is None:
        return default
    if not isinstance(value, dict):
        _bad("%s must be an object." % key)
    return value


def req_date(body, key):
    value = req_str(body, key)
    try:
        return date.fromisoformat(value)
    except ValueError:
        _bad("%s must be an ISO date (YYYY-MM-DD)." % key)


def parse_datetime(value, key):
    if not isinstance(value, str) or value.strip() == "":
        _bad("%s must be an ISO 8601 datetime string." % key)
    raw = value.strip()
    candidate = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        _bad("%s must be an ISO 8601 datetime string." % key)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def req_datetime(body, key):
    value = body.get(key, _MISSING)
    if value is _MISSING or value is None:
        _bad("%s is required." % key)
    return parse_datetime(value, key)


def to_decimal(value):
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        _bad("Invalid numeric value.")
