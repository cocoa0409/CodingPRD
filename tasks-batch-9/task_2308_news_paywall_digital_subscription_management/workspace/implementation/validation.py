"""Request-body shape validation (PRD 2.8 step 4 -> ERR_INVALID_REQUEST)."""
from decimal import Decimal, InvalidOperation

from flask import request

from clock import parse_date, parse_datetime
from errors import fail

_MISSING = object()


def body():
    payload = request.get_json(silent=True)
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        fail("ERR_INVALID_REQUEST", "The request body must be a JSON object.")
    return payload


def _present(data, key):
    return key in data and data[key] is not None


def require_present(data, *keys):
    for key in keys:
        if not _present(data, key):
            fail("ERR_INVALID_REQUEST", "Field '%s' is required." % key)


def get_string(data, key, required=False, min_len=None, max_len=None, default=None):
    if not _present(data, key):
        if required:
            fail("ERR_INVALID_REQUEST", "Field '%s' is required." % key)
        return default
    value = data[key]
    if not isinstance(value, str):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a string." % key)
    if min_len is not None and len(value) < min_len:
        fail("ERR_INVALID_REQUEST", "Field '%s' is too short." % key)
    if max_len is not None and len(value) > max_len:
        fail("ERR_INVALID_REQUEST", "Field '%s' is too long." % key)
    return value


def get_enum(data, key, allowed, required=False, default=None):
    if not _present(data, key):
        if required:
            fail("ERR_INVALID_REQUEST", "Field '%s' is required." % key)
        return default
    value = data[key]
    if not isinstance(value, str) or value not in allowed:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be one of %s." % (key, ", ".join(allowed)))
    return value


def get_int(data, key, required=False, default=None, minimum=0, maximum=None):
    if not _present(data, key):
        if required:
            fail("ERR_INVALID_REQUEST", "Field '%s' is required." % key)
        return default
    value = data[key]
    if isinstance(value, bool) or not isinstance(value, int):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be an integer." % key)
    if minimum is not None and value < minimum:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be >= %s." % (key, minimum))
    if maximum is not None and value > maximum:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be <= %s." % (key, maximum))
    return value


def get_bool(data, key, required=False, default=None):
    if not _present(data, key):
        if required:
            fail("ERR_INVALID_REQUEST", "Field '%s' is required." % key)
        return default
    value = data[key]
    if not isinstance(value, bool):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a boolean." % key)
    return value


def get_fraction(data, key, required=False, default=None):
    """Discount fractions must be numbers inside [0, 1] inclusive."""
    if not _present(data, key):
        if required:
            fail("ERR_INVALID_REQUEST", "Field '%s' is required." % key)
        return default
    value = data[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a number." % key)
    try:
        decimal_value = Decimal(str(value))
    except (InvalidOperation, ValueError):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a number." % key)
    if decimal_value < 0 or decimal_value > 1:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be between 0 and 1 inclusive." % key)
    return decimal_value


def get_date(data, key, required=False, default=None):
    if not _present(data, key):
        if required:
            fail("ERR_INVALID_REQUEST", "Field '%s' is required." % key)
        return default
    parsed = parse_date(data[key])
    if parsed is None:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be an ISO date (YYYY-MM-DD)." % key)
    return parsed


def get_datetime(data, key, required=False, default=None):
    if not _present(data, key):
        if required:
            fail("ERR_INVALID_REQUEST", "Field '%s' is required." % key)
        return default
    parsed = parse_datetime(data[key])
    if parsed is None:
        fail(
            "ERR_INVALID_REQUEST",
            "Field '%s' must be an RFC 3339 instant with a trailing Z." % key,
        )
    return parsed


def get_id(data, key, required=False, default=None):
    return get_string(data, key, required=required, min_len=1, default=default)


def get_string_array(data, key, allowed=None, default=None):
    if not _present(data, key):
        return list(default) if default is not None else None
    value = data[key]
    if not isinstance(value, list):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be an array." % key)
    for item in value:
        if not isinstance(item, str):
            fail("ERR_INVALID_REQUEST", "Field '%s' must be an array of strings." % key)
        if allowed is not None and item not in allowed:
            fail("ERR_INVALID_REQUEST", "Field '%s' contains an unknown value." % key)
    return list(value)


def get_step_up_schedule(data, key="step_up_schedule"):
    if not _present(data, key):
        return []
    value = data[key]
    if not isinstance(value, list):
        fail("ERR_INVALID_REQUEST", "Field 'step_up_schedule' must be an array.")
    entries = []
    for item in value:
        if not isinstance(item, dict):
            fail(
                "ERR_INVALID_REQUEST",
                "Each step_up_schedule entry must be an object with from_cycle and price_cents.",
            )
        from_cycle = get_int(item, "from_cycle", required=True, minimum=0)
        price_cents = get_int(item, "price_cents", required=True, minimum=0)
        entries.append({"from_cycle": from_cycle, "price_cents": price_cents})
    return entries


def is_lower_slug(value):
    if not value:
        return False
    return all(ch.islower() or ch.isdigit() or ch in "-_" for ch in value)
