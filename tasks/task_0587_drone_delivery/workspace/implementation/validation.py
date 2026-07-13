"""Request-shape validation (PRD 2.11 step 3 -> ERR_INVALID_REQUEST, 422)."""
from decimal import Decimal

from flask import request

from errors import err
from timeutil import parse

MISSING = object()


def bad(msg):
    return err("ERR_INVALID_REQUEST", msg)


def body():
    """The JSON request body; a missing body is treated as an empty object."""
    if not request.data:
        return {}
    try:
        data = request.get_json(force=True, silent=False)
    except Exception:
        raise bad("Request body is not valid JSON.")
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise bad("Request body must be a JSON object.")
    return data


def _present(data, key, required, default):
    if key not in data or data[key] is None:
        if required:
            raise bad("Field '%s' is required." % key)
        return default
    return MISSING


def as_string(data, key, required=True, default=None, allow_empty=True):
    fallback = _present(data, key, required, default)
    if fallback is not MISSING:
        return fallback
    value = data[key]
    if not isinstance(value, str):
        raise bad("Field '%s' must be a string." % key)
    if not allow_empty and not value.strip():
        raise bad("Field '%s' must not be empty." % key)
    return value


def as_number(data, key, required=True, default=None, gt=None, gte=None, lte=None):
    fallback = _present(data, key, required, default)
    if fallback is not MISSING:
        return None if fallback is None else Decimal(str(fallback))
    value = data[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise bad("Field '%s' must be a number." % key)
    dec = Decimal(str(value))
    _check_bounds(key, dec, gt, gte, lte)
    return dec


def as_integer(data, key, required=True, default=None, gt=None, gte=None, lte=None):
    fallback = _present(data, key, required, default)
    if fallback is not MISSING:
        return fallback
    value = data[key]
    if isinstance(value, bool) or not isinstance(value, int):
        raise bad("Field '%s' must be an integer." % key)
    _check_bounds(key, Decimal(value), gt, gte, lte)
    return value


def _check_bounds(key, dec, gt, gte, lte):
    if gt is not None and not dec > Decimal(str(gt)):
        raise bad("Field '%s' must be greater than %s." % (key, gt))
    if gte is not None and not dec >= Decimal(str(gte)):
        raise bad("Field '%s' must be at least %s." % (key, gte))
    if lte is not None and not dec <= Decimal(str(lte)):
        raise bad("Field '%s' must be at most %s." % (key, lte))


def as_enum(data, key, allowed, required=True, default=None):
    fallback = _present(data, key, required, default)
    if fallback is not MISSING:
        return fallback
    value = data[key]
    if not isinstance(value, str) or value not in allowed:
        raise bad("Field '%s' must be one of %s." % (key, ", ".join(allowed)))
    return value


def as_datetime(data, key, required=True, default=None):
    fallback = _present(data, key, required, default)
    if fallback is not MISSING:
        return fallback
    value = data[key]
    parsed = parse(value) if isinstance(value, str) else None
    if parsed is None:
        raise bad("Field '%s' must be an ISO 8601 timestamp." % key)
    return parsed


def as_string_list(data, key, required=True, default=None):
    fallback = _present(data, key, required, default)
    if fallback is not MISSING:
        return fallback
    value = data[key]
    if not isinstance(value, list) or any(not isinstance(v, str) for v in value):
        raise bad("Field '%s' must be an array of strings." % key)
    return list(value)


# --- query parameters -----------------------------------------------------


def pagination():
    """limit (default 10, 1..100) and offset (default 0, >= 0) — PRD 2.3."""
    limit = _query_int("limit", 10)
    offset = _query_int("offset", 0)
    if limit < 1 or limit > 100:
        raise bad("Query parameter 'limit' must be between 1 and 100.")
    if offset < 0:
        raise bad("Query parameter 'offset' must not be negative.")
    return limit, offset


def _query_int(name, default):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        raise bad("Query parameter '%s' must be an integer." % name)


def query_enum(name, allowed):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    if raw not in allowed:
        raise bad("Query parameter '%s' must be one of %s." % (name, ", ".join(allowed)))
    return raw


def query_str(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    return raw


def paginate(rows, limit, offset):
    return rows[offset:offset + limit], len(rows)
