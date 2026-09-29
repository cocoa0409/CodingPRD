"""Payload well-formedness helpers (PRD Section 2.9 check 5 -> ERR_INVALID_REQUEST)."""
from flask import request

from errors import ApiError
from timeutil import parse_iso

PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0


def bad(message):
    raise ApiError("ERR_INVALID_REQUEST", message)


def body():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return {}
    return payload


def raw(payload, field):
    return payload.get(field)


def _present(payload, field, required):
    if field not in payload or payload[field] is None:
        if required:
            bad("'%s' is required" % field)
        return False
    return True


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _is_num(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def string_field(payload, field, required=True, min_len=1, max_len=None, nullable=False):
    if not _present(payload, field, required):
        return None
    value = payload[field]
    if value is None and nullable:
        return None
    if not isinstance(value, str):
        bad("'%s' must be a string" % field)
    if len(value) < min_len:
        bad("'%s' must be at least %d characters" % (field, min_len))
    if max_len is not None and len(value) > max_len:
        bad("'%s' must be at most %d characters" % (field, max_len))
    return value


def int_field(payload, field, required=True, minimum=None, maximum=None):
    if not _present(payload, field, required):
        return None
    value = payload[field]
    if not _is_int(value):
        bad("'%s' must be an integer" % field)
    if minimum is not None and value < minimum:
        bad("'%s' must be at least %s" % (field, minimum))
    if maximum is not None and value > maximum:
        bad("'%s' must be at most %s" % (field, maximum))
    return value


def number_field(payload, field, required=True, gt=None, ge=None, le=None):
    if not _present(payload, field, required):
        return None
    value = payload[field]
    if not _is_num(value):
        bad("'%s' must be a number" % field)
    if gt is not None and not value > gt:
        bad("'%s' must be greater than %s" % (field, gt))
    if ge is not None and value < ge:
        bad("'%s' must be at least %s" % (field, ge))
    if le is not None and value > le:
        bad("'%s' must be at most %s" % (field, le))
    return value


def enum_field(payload, field, allowed, required=True):
    if not _present(payload, field, required):
        return None
    value = payload[field]
    if not isinstance(value, str) or value not in allowed:
        bad("'%s' must be one of %s" % (field, ", ".join(allowed)))
    return value


def enum_array_field(payload, field, allowed, required=True, allow_empty=False):
    if not _present(payload, field, required):
        return None
    value = payload[field]
    if not isinstance(value, list):
        bad("'%s' must be an array" % field)
    if not allow_empty and len(value) == 0:
        bad("'%s' must not be empty" % field)
    for item in value:
        if not isinstance(item, str) or item not in allowed:
            bad("'%s' members must be drawn from %s" % (field, ", ".join(allowed)))
    if len(set(value)) != len(value):
        bad("'%s' must not contain duplicate elements" % field)
    return list(value)


def datetime_field(payload, field, required=True):
    if not _present(payload, field, required):
        return None
    value = payload[field]
    parsed = parse_iso(value)
    if parsed is None:
        bad("'%s' must be an ISO 8601 UTC datetime" % field)
    return parsed


def window_fields(payload):
    start = datetime_field(payload, "window_start")
    end = datetime_field(payload, "window_end")
    if not end > start:
        bad("'window_end' must be strictly later than 'window_start'")
    return start, end


def pagination():
    args = request.args
    limit = PAGINATION_DEFAULT_LIMIT
    offset = PAGINATION_DEFAULT_OFFSET
    if "limit" in args:
        rawv = args.get("limit")
        try:
            limit = int(str(rawv).strip())
        except (TypeError, ValueError):
            bad("'limit' must be an integer")
        if limit < PAGINATION_MIN_LIMIT or limit > PAGINATION_MAX_LIMIT:
            bad("'limit' must be between %d and %d inclusive" % (PAGINATION_MIN_LIMIT, PAGINATION_MAX_LIMIT))
    if "offset" in args:
        rawv = args.get("offset")
        try:
            offset = int(str(rawv).strip())
        except (TypeError, ValueError):
            bad("'offset' must be an integer")
        if offset < 0:
            bad("'offset' must be at least 0")
    return limit, offset


def enum_arg(name, allowed):
    value = request.args.get(name)
    if value is None:
        return None
    if value not in allowed:
        bad("'%s' must be one of %s" % (name, ", ".join(allowed)))
    return value


def str_arg(name):
    return request.args.get(name)
