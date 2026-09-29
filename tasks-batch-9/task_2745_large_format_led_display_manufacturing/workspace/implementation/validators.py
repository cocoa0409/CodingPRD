"""Request-shape validation (PRD section 2.7 rung 3 -> ERR_VALIDATION_FAILED)."""

import json
from decimal import Decimal

from flask import request

import store
from errors import ApiError
from numeric import decimal_places

MISSING = object()


def fail(message="The request is malformed."):
    raise ApiError("ERR_VALIDATION_FAILED", message)


def body():
    """Parse the request body as JSON with exact decimals.

    An absent or blank body is treated as an empty object so that no-body
    endpoints work regardless of Content-Type.
    """
    raw = request.get_data(as_text=True)
    if raw is None or raw.strip() == "":
        return {}
    try:
        parsed = json.loads(raw, parse_float=Decimal)
    except ValueError:
        fail("Request body is not valid JSON.")
    if not isinstance(parsed, dict):
        fail("Request body must be a JSON object.")
    return parsed


def present(payload, name):
    return name in payload and payload[name] is not None


def forbid(payload, name, message=None):
    if name in payload and payload[name] is not None:
        fail(message or ("Field '%s' must be omitted." % name))


# ---------------------------------------------------------------------------
# Scalars
# ---------------------------------------------------------------------------
def get_str(payload, name, required=True, min_len=1, max_len=None, default=None):
    if not present(payload, name):
        if required:
            fail("Field '%s' is required." % name)
        return default
    value = payload[name]
    if not isinstance(value, str):
        fail("Field '%s' must be a string." % name)
    if min_len is not None and len(value) < min_len:
        fail("Field '%s' is shorter than %d characters." % (name, min_len))
    if max_len is not None and len(value) > max_len:
        fail("Field '%s' is longer than %d characters." % (name, max_len))
    return value


def get_id(payload, name, required=True):
    if not present(payload, name):
        if required:
            fail("Field '%s' is required." % name)
        return None
    value = payload[name]
    if not isinstance(value, str) or value == "":
        fail("Field '%s' must be a non-empty string id." % name)
    return value


def get_int(payload, name, required=True, minimum=None, maximum=None,
            choices=None, default=None):
    if not present(payload, name):
        if required:
            fail("Field '%s' is required." % name)
        return default
    value = payload[name]
    if isinstance(value, bool):
        fail("Field '%s' must be an integer." % name)
    if isinstance(value, int):
        ivalue = value
    elif isinstance(value, Decimal):
        if value != value.to_integral_value():
            fail("Field '%s' must be an integer." % name)
        ivalue = int(value)
    else:
        fail("Field '%s' must be an integer." % name)
    if minimum is not None and ivalue < minimum:
        fail("Field '%s' must be >= %s." % (name, minimum))
    if maximum is not None and ivalue > maximum:
        fail("Field '%s' must be <= %s." % (name, maximum))
    if choices is not None and ivalue not in choices:
        fail("Field '%s' must be one of %s." % (name, sorted(choices)))
    return ivalue


def get_num(payload, name, required=True, minimum=None, maximum=None,
            exclusive_min=None, exclusive_max=None, places=None, default=None):
    if not present(payload, name):
        if required:
            fail("Field '%s' is required." % name)
        return default
    value = payload[name]
    if isinstance(value, bool):
        fail("Field '%s' must be a number." % name)
    if isinstance(value, int):
        value = Decimal(value)
    elif isinstance(value, Decimal):
        pass
    elif isinstance(value, float):
        value = Decimal(str(value))
    else:
        fail("Field '%s' must be a number." % name)
    if not value.is_finite():
        fail("Field '%s' must be a finite number." % name)
    if minimum is not None and value < minimum:
        fail("Field '%s' must be >= %s." % (name, minimum))
    if maximum is not None and value > maximum:
        fail("Field '%s' must be <= %s." % (name, maximum))
    if exclusive_min is not None and value <= exclusive_min:
        fail("Field '%s' must be > %s." % (name, exclusive_min))
    if exclusive_max is not None and value >= exclusive_max:
        fail("Field '%s' must be < %s." % (name, exclusive_max))
    if places is not None and decimal_places(value) > places:
        fail("Field '%s' allows at most %d decimal places." % (name, places))
    return value


def get_enum(payload, name, allowed, required=True, default=None):
    if not present(payload, name):
        if required:
            fail("Field '%s' is required." % name)
        return default
    value = payload[name]
    if not isinstance(value, str) or value not in allowed:
        fail("Field '%s' must be one of %s." % (name, list(allowed)))
    return value


def get_bool(payload, name, required=True, default=None):
    if not present(payload, name):
        if required:
            fail("Field '%s' is required." % name)
        return default
    value = payload[name]
    if not isinstance(value, bool):
        fail("Field '%s' must be a boolean." % name)
    return value


def get_dt(payload, name, required=True, default=None):
    if not present(payload, name):
        if required:
            fail("Field '%s' is required." % name)
        return default
    value = payload[name]
    if not isinstance(value, str):
        fail("Field '%s' must be an ISO 8601 datetime string." % name)
    canon = store.canon_dt(value)
    if canon is None:
        fail("Field '%s' must be an ISO 8601 datetime string." % name)
    return canon


def get_window(payload):
    """window_start / window_end with the rung-3 ordering check."""
    start = get_dt(payload, "window_start")
    end = get_dt(payload, "window_end")
    if store.ms(end) <= store.ms(start):
        fail("window_end must be strictly later than window_start.")
    return start, end


# ---------------------------------------------------------------------------
# Query parameters
# ---------------------------------------------------------------------------
def pagination():
    limit = 10
    offset = 0
    raw_limit = request.args.get("limit")
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            fail("Query parameter 'limit' must be an integer.")
        if limit < 1 or limit > 100:
            fail("Query parameter 'limit' must be between 1 and 100.")
    raw_offset = request.args.get("offset")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            fail("Query parameter 'offset' must be an integer.")
        if offset < 0:
            fail("Query parameter 'offset' must not be negative.")
    return limit, offset


def query_enum(name, allowed):
    value = request.args.get(name)
    if value is None:
        return None
    if value not in allowed:
        fail("Query parameter '%s' must be one of %s." % (name, list(allowed)))
    return value


def query_str(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    return value
