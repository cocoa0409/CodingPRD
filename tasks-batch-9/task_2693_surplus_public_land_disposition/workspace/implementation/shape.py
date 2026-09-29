"""Request-shape validation (PRD 2.10 shape layer): required fields present,
enum members, non-negative whole-cent money, parseable ISO 8601 instants and
declared list-length / numeric ranges.  Every failure is ERR_INVALID_REQUEST.
"""

from flask import request

import clockmod
from errors import fail

MISSING = object()


def body():
    if not request.data:
        return {}
    try:
        payload = request.get_json(force=True, silent=False)
    except Exception:
        fail("ERR_INVALID_REQUEST", "The request body is not valid JSON.")
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        fail("ERR_INVALID_REQUEST", "The request body must be a JSON object.")
    return payload


def present(payload, field):
    return field in payload and payload[field] is not None


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def req_str(payload, field, min_len=1, max_len=None):
    if not present(payload, field):
        fail("ERR_INVALID_REQUEST", "%s is required." % field)
    return opt_str(payload, field, min_len, max_len)


def opt_str(payload, field, min_len=1, max_len=None, default=None):
    if not present(payload, field):
        return default
    value = payload[field]
    if not isinstance(value, str):
        fail("ERR_INVALID_REQUEST", "%s must be a string." % field)
    if min_len is not None and len(value) < min_len:
        fail("ERR_INVALID_REQUEST", "%s must be at least %d characters." % (field, min_len))
    if max_len is not None and len(value) > max_len:
        fail("ERR_INVALID_REQUEST", "%s must be at most %d characters." % (field, max_len))
    return value


def req_enum(payload, field, members):
    if not present(payload, field):
        fail("ERR_INVALID_REQUEST", "%s is required." % field)
    return opt_enum(payload, field, members)


def opt_enum(payload, field, members, default=None):
    if not present(payload, field):
        return default
    value = payload[field]
    if not isinstance(value, str) or value not in members:
        fail("ERR_INVALID_REQUEST", "%s must be one of %s." % (field, ", ".join(members)))
    return value


def req_cents(payload, field):
    if not present(payload, field):
        fail("ERR_INVALID_REQUEST", "%s is required." % field)
    return opt_cents(payload, field)


def opt_cents(payload, field, default=None):
    if not present(payload, field):
        return default
    value = payload[field]
    if not _is_int(value):
        fail("ERR_INVALID_REQUEST", "%s must be an integer number of cents." % field)
    if value < 0:
        fail("ERR_INVALID_REQUEST", "%s may not be negative." % field)
    return value


def req_int(payload, field, minimum=None, maximum=None):
    if not present(payload, field):
        fail("ERR_INVALID_REQUEST", "%s is required." % field)
    return opt_int(payload, field, minimum, maximum)


def opt_int(payload, field, minimum=None, maximum=None, default=None):
    if not present(payload, field):
        return default
    value = payload[field]
    if not _is_int(value):
        fail("ERR_INVALID_REQUEST", "%s must be an integer." % field)
    if minimum is not None and value < minimum:
        fail("ERR_INVALID_REQUEST", "%s must be at least %s." % (field, minimum))
    if maximum is not None and value > maximum:
        fail("ERR_INVALID_REQUEST", "%s must be at most %s." % (field, maximum))
    return value


def req_bool(payload, field):
    if not present(payload, field):
        fail("ERR_INVALID_REQUEST", "%s is required." % field)
    return opt_bool(payload, field)


def opt_bool(payload, field, default=None):
    if not present(payload, field):
        return default
    value = payload[field]
    if not isinstance(value, bool):
        fail("ERR_INVALID_REQUEST", "%s must be a boolean." % field)
    return value


def req_instant(payload, field):
    if not present(payload, field):
        fail("ERR_INVALID_REQUEST", "%s is required." % field)
    return opt_instant(payload, field)


def opt_instant(payload, field):
    """Return (datetime, raw_string) or (None, None) when absent."""
    if not present(payload, field):
        return None, None
    value = payload[field]
    if not isinstance(value, str):
        fail("ERR_INVALID_REQUEST", "%s must be an ISO 8601 UTC instant." % field)
    parsed = clockmod.parse(value)
    if parsed is None:
        fail("ERR_INVALID_REQUEST", "%s must be an ISO 8601 UTC instant." % field)
    return parsed, value


def req_positive_number(payload, field):
    if not present(payload, field):
        fail("ERR_INVALID_REQUEST", "%s is required." % field)
    value = payload[field]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        fail("ERR_INVALID_REQUEST", "%s must be a number." % field)
    if value <= 0:
        fail("ERR_INVALID_REQUEST", "%s must be strictly greater than zero." % field)
    return value


def opt_fraction(payload, field, default=None):
    """A decimal fraction between 0 and 1 inclusive with at most 4 decimals."""
    if not present(payload, field):
        return default
    value = payload[field]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        fail("ERR_INVALID_REQUEST", "%s must be a number between 0 and 1." % field)
    if value < 0 or value > 1:
        fail("ERR_INVALID_REQUEST", "%s must be between 0 and 1 inclusive." % field)
    text = repr(float(value))
    if "e" in text or "E" in text:
        fail("ERR_INVALID_REQUEST", "%s carries too many decimal places." % field)
    if "." in text and len(text.split(".")[1].rstrip("0")) > 4:
        fail("ERR_INVALID_REQUEST", "%s may carry at most four decimal places." % field)
    return value


def req_fraction(payload, field):
    if not present(payload, field):
        fail("ERR_INVALID_REQUEST", "%s is required." % field)
    return opt_fraction(payload, field)


def req_str_list(payload, field, min_items, max_items, distinct=False):
    if not present(payload, field):
        fail("ERR_INVALID_REQUEST", "%s is required." % field)
    value = payload[field]
    if not isinstance(value, list):
        fail("ERR_INVALID_REQUEST", "%s must be a list." % field)
    if len(value) < min_items or len(value) > max_items:
        fail("ERR_INVALID_REQUEST",
             "%s must hold between %d and %d entries." % (field, min_items, max_items))
    for entry in value:
        if not isinstance(entry, str) or not entry:
            fail("ERR_INVALID_REQUEST", "%s entries must be non-empty strings." % field)
    if distinct and len(set(value)) != len(value):
        fail("ERR_INVALID_REQUEST", "%s entries must be distinct." % field)
    return value


def query_enum(field, members):
    value = request.args.get(field)
    if value is None:
        return None
    if value not in members:
        fail("ERR_INVALID_REQUEST", "%s must be one of %s." % (field, ", ".join(members)))
    return value


def query_bool(field):
    value = request.args.get(field)
    if value is None:
        return None
    lowered = value.lower()
    if lowered in ("true", "1"):
        return True
    if lowered in ("false", "0"):
        return False
    fail("ERR_INVALID_REQUEST", "%s must be a boolean." % field)


def query_int(field):
    value = request.args.get(field)
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        fail("ERR_INVALID_REQUEST", "%s must be an integer." % field)


def query_str(field):
    return request.args.get(field)
