"""Request body shape and pagination validation (section 2.8 rank 5)."""

from flask import request

import clock
from constants import (
    PAGINATION_DEFAULT_LIMIT,
    PAGINATION_DEFAULT_OFFSET,
    PAGINATION_MAX_LIMIT,
    PAGINATION_MIN_LIMIT,
)
from errors import ApiError

_MISSING = object()


def bad(message):
    raise ApiError("ERR_INVALID_REQUEST", message)


def body():
    if not request.data:
        return {}
    payload = request.get_json(silent=True)
    if payload is None:
        bad("The request body is not valid JSON.")
    if not isinstance(payload, dict):
        bad("The request body must be a JSON object.")
    return payload


def present(payload, name):
    return name in payload and payload[name] is not None


# ------------------------------------------------------------------ scalars


def req_str(payload, name, min_len=1, max_len=None):
    value = payload.get(name, _MISSING)
    if value is _MISSING or value is None:
        bad("%s is required." % name)
    if not isinstance(value, str):
        bad("%s must be a string." % name)
    if len(value) < min_len or (value.strip() == "" and min_len > 0):
        bad("%s must be a non-empty string." % name)
    if max_len is not None and len(value) > max_len:
        bad("%s must be at most %d characters." % (name, max_len))
    return value


def opt_str(payload, name, default=None, max_len=None):
    if not present(payload, name):
        return default
    value = payload[name]
    if not isinstance(value, str):
        bad("%s must be a string." % name)
    if max_len is not None and len(value) > max_len:
        bad("%s must be at most %d characters." % (name, max_len))
    return value


def _check_int(name, value, minimum, maximum):
    if isinstance(value, bool) or not isinstance(value, int):
        bad("%s must be an integer." % name)
    if minimum is not None and value < minimum:
        bad("%s must be at least %s." % (name, minimum))
    if maximum is not None and value > maximum:
        bad("%s must be at most %s." % (name, maximum))
    return value


def req_int(payload, name, minimum=None, maximum=None):
    value = payload.get(name, _MISSING)
    if value is _MISSING or value is None:
        bad("%s is required." % name)
    return _check_int(name, value, minimum, maximum)


def opt_int(payload, name, default=None, minimum=None, maximum=None):
    if not present(payload, name):
        return default
    return _check_int(name, payload[name], minimum, maximum)


def req_bool(payload, name):
    value = payload.get(name, _MISSING)
    if value is _MISSING or value is None:
        bad("%s is required." % name)
    if not isinstance(value, bool):
        bad("%s must be a boolean." % name)
    return value


def opt_bool(payload, name, default=None):
    if not present(payload, name):
        return default
    value = payload[name]
    if not isinstance(value, bool):
        bad("%s must be a boolean." % name)
    return value


def req_enum(payload, name, allowed):
    value = payload.get(name, _MISSING)
    if value is _MISSING or value is None:
        bad("%s is required." % name)
    if not isinstance(value, str) or value not in allowed:
        bad("%s must be one of %s." % (name, ", ".join(allowed)))
    return value


def opt_enum(payload, name, allowed, default=None):
    if not present(payload, name):
        return default
    value = payload[name]
    if not isinstance(value, str) or value not in allowed:
        bad("%s must be one of %s." % (name, ", ".join(allowed)))
    return value


def req_date(payload, name):
    value = payload.get(name, _MISSING)
    if value is _MISSING or value is None:
        bad("%s is required." % name)
    if not isinstance(value, str) or clock.parse_date(value) is None:
        bad("%s must be an ISO 8601 calendar date (YYYY-MM-DD)." % name)
    return value


def opt_date(payload, name, default=None):
    if not present(payload, name):
        return default
    value = payload[name]
    if not isinstance(value, str) or clock.parse_date(value) is None:
        bad("%s must be an ISO 8601 calendar date (YYYY-MM-DD)." % name)
    return value


def req_id(payload, name):
    value = payload.get(name, _MISSING)
    if value is _MISSING or value is None:
        bad("%s is required." % name)
    if not isinstance(value, str) or value.strip() == "":
        bad("%s must be a resource identifier string." % name)
    return value


def req_str_list(payload, name, allowed=None, min_items=1):
    value = payload.get(name, _MISSING)
    if value is _MISSING or value is None:
        bad("%s is required." % name)
    if not isinstance(value, list):
        bad("%s must be an array." % name)
    if len(value) < min_items:
        bad("%s must contain at least %d item(s)." % (name, min_items))
    for item in value:
        if not isinstance(item, str):
            bad("%s must be an array of strings." % name)
        if allowed is not None and item not in allowed:
            bad("%s contains an unrecognised member." % name)
    return value


def opt_str_list(payload, name, default=None, allowed=None):
    if not present(payload, name):
        return default
    value = payload[name]
    if not isinstance(value, list):
        bad("%s must be an array." % name)
    for item in value:
        if not isinstance(item, str):
            bad("%s must be an array of strings." % name)
        if allowed is not None and item not in allowed:
            bad("%s contains an unrecognised member." % name)
    return value


# ------------------------------------------------------------------ pagination


def _query_int(name, default, minimum, maximum):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        bad("%s must be an integer." % name)
    if minimum is not None and value < minimum:
        bad("%s must be at least %s." % (name, minimum))
    if maximum is not None and value > maximum:
        bad("%s must be at most %s." % (name, maximum))
    return value


def pagination():
    limit = _query_int(
        "limit", PAGINATION_DEFAULT_LIMIT, PAGINATION_MIN_LIMIT, PAGINATION_MAX_LIMIT
    )
    offset = _query_int("offset", PAGINATION_DEFAULT_OFFSET, 0, None)
    return limit, offset


def paginate(rows):
    """Apply limit/offset to an already-filtered, already-ordered row list."""
    limit, offset = pagination()
    total = len(rows)
    items = rows[offset : offset + limit]
    return {
        "items": items,
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(items) < total,
    }


def query_filter(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    return value
