"""Body structure and field-value validation (PRD 2.6 priorities 4 and 5)."""
import json

from flask import request

from errors import ApiError
from response import (PAGINATION_DEFAULT_LIMIT, PAGINATION_DEFAULT_OFFSET,
                      PAGINATION_MAX_LIMIT, PAGINATION_MIN_LIMIT)
from timeutil import dec, parse_date


def _bad_request(message):
    return ApiError("ERR_INVALID_REQUEST", message)


def _bad_value(message):
    return ApiError("ERR_INVALID_FIELD_VALUE", message)


def read_body(required=(), optional=()):
    """Parse the JSON body, then enforce the unknown/missing-field rules."""
    raw = request.get_data(cache=True, as_text=True)
    if raw is None or raw.strip() == "":
        body = {}
    else:
        try:
            body = json.loads(raw)
        except Exception:
            raise _bad_request("Request body is not well-formed JSON.")
        if not isinstance(body, dict):
            raise _bad_request("Request body must be a JSON object.")

    allowed = set(required) | set(optional)
    for key in body.keys():
        if key not in allowed:
            raise _bad_request("Unknown field '%s'." % key)
    for key in required:
        if key not in body or body[key] is None:
            raise _bad_request("Field '%s' is required." % key)
    return body


def present(body, key):
    return key in body and body[key] is not None


# ---------------------------------------------------------------- scalars ---

def v_string(body, key, min_len=None, max_len=None, default=None):
    if not present(body, key):
        return default
    value = body[key]
    if not isinstance(value, str):
        raise _bad_value("Field '%s' must be a string." % key)
    if min_len is not None and len(value) < min_len:
        raise _bad_value("Field '%s' must be at least %d characters." % (key, min_len))
    if max_len is not None and len(value) > max_len:
        raise _bad_value("Field '%s' must be at most %d characters." % (key, max_len))
    return value


def v_int(body, key, minimum=None, maximum=None, default=None):
    if not present(body, key):
        return default
    value = body[key]
    if isinstance(value, bool) or not isinstance(value, int):
        raise _bad_value("Field '%s' must be an integer." % key)
    if minimum is not None and value < minimum:
        raise _bad_value("Field '%s' must be >= %s." % (key, minimum))
    if maximum is not None and value > maximum:
        raise _bad_value("Field '%s' must be <= %s." % (key, maximum))
    return value


def v_number(body, key, minimum=None, maximum=None, exclusive_min=None, default=None):
    if not present(body, key):
        return default
    value = body[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _bad_value("Field '%s' must be a number." % key)
    number = dec(value)
    if exclusive_min is not None and number <= dec(exclusive_min):
        raise _bad_value("Field '%s' must be greater than %s." % (key, exclusive_min))
    if minimum is not None and number < dec(minimum):
        raise _bad_value("Field '%s' must be >= %s." % (key, minimum))
    if maximum is not None and number > dec(maximum):
        raise _bad_value("Field '%s' must be <= %s." % (key, maximum))
    return value


def v_bool(body, key, default=None):
    if not present(body, key):
        return default
    value = body[key]
    if not isinstance(value, bool):
        raise _bad_value("Field '%s' must be a boolean." % key)
    return value


def v_enum(body, key, allowed, default=None):
    if not present(body, key):
        return default
    value = body[key]
    if not isinstance(value, str) or value not in allowed:
        raise _bad_value("Field '%s' must be one of %s." % (key, ", ".join(allowed)))
    return value


def v_instant(body, key, default=None):
    """Validate an ISO-8601 instant; the caller-supplied text is echoed verbatim."""
    if not present(body, key):
        return default
    value = body[key]
    if not isinstance(value, str) or parse_date(value) is None:
        raise _bad_value("Field '%s' must be an ISO 8601 timestamp." % key)
    return value


def v_id(body, key, default=None):
    if not present(body, key):
        return default
    value = body[key]
    if not isinstance(value, str) or value.strip() == "":
        raise _bad_value("Field '%s' must be an identifier string." % key)
    return value


def v_not_after(raw, key, limit_dt):
    """Reject an instant that lies after the given bound (used for the clock)."""
    moment = parse_date(raw)
    if moment > limit_dt:
        raise _bad_value("Field '%s' may not be later than the logical clock." % key)
    return raw


def v_after(raw, key, limit_dt):
    moment = parse_date(raw)
    if moment <= limit_dt:
        raise _bad_value("Field '%s' must be strictly later than the logical clock." % key)
    return raw


# ------------------------------------------------------------- query args ---

def read_pagination():
    limit = PAGINATION_DEFAULT_LIMIT
    offset = PAGINATION_DEFAULT_OFFSET
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is not None and raw_limit != "":
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise _bad_value("Query parameter 'limit' must be an integer.")
        if limit < PAGINATION_MIN_LIMIT or limit > PAGINATION_MAX_LIMIT:
            raise _bad_value("Query parameter 'limit' must be between %d and %d."
                             % (PAGINATION_MIN_LIMIT, PAGINATION_MAX_LIMIT))
    if raw_offset is not None and raw_offset != "":
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise _bad_value("Query parameter 'offset' must be an integer.")
        if offset < 0:
            raise _bad_value("Query parameter 'offset' must be >= 0.")
    return limit, offset


def q_string(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    return value


def q_enum(name, allowed):
    value = q_string(name)
    if value is None:
        return None
    if value not in allowed:
        raise _bad_value("Query parameter '%s' must be one of %s." % (name, ", ".join(allowed)))
    return value


def q_bool(name):
    value = q_string(name)
    if value is None:
        return None
    lowered = value.lower()
    if lowered in ("true", "1"):
        return True
    if lowered in ("false", "0"):
        return False
    raise _bad_value("Query parameter '%s' must be a boolean." % name)


def q_int(name, minimum=None):
    value = q_string(name)
    if value is None:
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        raise _bad_value("Query parameter '%s' must be an integer." % name)
    if minimum is not None and parsed < minimum:
        raise _bad_value("Query parameter '%s' must be >= %s." % (name, minimum))
    return parsed
