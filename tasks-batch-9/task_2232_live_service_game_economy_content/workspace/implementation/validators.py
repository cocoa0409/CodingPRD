"""Body / query schema conformance (precedence step 5 -> ERR_INVALID_REQUEST)."""
from flask import request

from config import PAGE_LIMIT_DEFAULT, PAGE_LIMIT_MAX, PAGE_LIMIT_MIN, PAGE_OFFSET_DEFAULT
from errors import fail
from util import parse_iso

_MISSING = object()


def body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        fail("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return data


def bad(field, why="is invalid"):
    fail("ERR_INVALID_REQUEST", "Field '%s' %s." % (field, why))


def _present(payload, name):
    value = payload.get(name, _MISSING)
    if value is _MISSING or value is None:
        return _MISSING
    return value


def req_string(payload, name, min_len=1, max_len=None):
    value = _present(payload, name)
    if value is _MISSING:
        bad(name, "is required")
    if not isinstance(value, str):
        bad(name, "must be a string")
    if min_len is not None and len(value) < min_len:
        bad(name, "is too short")
    if max_len is not None and len(value) > max_len:
        bad(name, "is too long")
    return value


def opt_string(payload, name, default=None, max_len=None):
    value = _present(payload, name)
    if value is _MISSING:
        return default
    if not isinstance(value, str):
        bad(name, "must be a string")
    if max_len is not None and len(value) > max_len:
        bad(name, "is too long")
    return value


def req_int(payload, name, minimum=None, maximum=None):
    value = _present(payload, name)
    if value is _MISSING:
        bad(name, "is required")
    return _as_int(name, value, minimum, maximum)


def opt_int(payload, name, default=None, minimum=None, maximum=None):
    value = _present(payload, name)
    if value is _MISSING:
        return default
    return _as_int(name, value, minimum, maximum)


def _as_int(name, value, minimum, maximum):
    if isinstance(value, bool) or not isinstance(value, int):
        bad(name, "must be an integer")
    if minimum is not None and value < minimum:
        bad(name, "is below its minimum")
    if maximum is not None and value > maximum:
        bad(name, "is above its maximum")
    return value


def req_enum(payload, name, allowed):
    value = _present(payload, name)
    if value is _MISSING:
        bad(name, "is required")
    if not isinstance(value, str) or value not in allowed:
        bad(name, "must be one of %s" % ", ".join(allowed))
    return value


def opt_enum(payload, name, allowed, default=None):
    value = _present(payload, name)
    if value is _MISSING:
        return default
    if not isinstance(value, str) or value not in allowed:
        bad(name, "must be one of %s" % ", ".join(allowed))
    return value


def req_bool(payload, name):
    value = _present(payload, name)
    if value is _MISSING:
        bad(name, "is required")
    if not isinstance(value, bool):
        bad(name, "must be a boolean")
    return value


def opt_bool(payload, name, default=False):
    value = _present(payload, name)
    if value is _MISSING:
        return default
    if not isinstance(value, bool):
        bad(name, "must be a boolean")
    return value


def req_datetime(payload, name):
    value = _present(payload, name)
    if value is _MISSING:
        bad(name, "is required")
    parsed = parse_iso(value)
    if parsed is None:
        bad(name, "must be an ISO 8601 instant")
    return parsed


def opt_datetime(payload, name, default=None):
    value = _present(payload, name)
    if value is _MISSING:
        return default
    parsed = parse_iso(value)
    if parsed is None:
        bad(name, "must be an ISO 8601 instant")
    return parsed


def pagination():
    limit = PAGE_LIMIT_DEFAULT
    offset = PAGE_OFFSET_DEFAULT
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is not None:
        limit = _query_int("limit", raw_limit)
        if limit < PAGE_LIMIT_MIN or limit > PAGE_LIMIT_MAX:
            bad("limit", "must be between %d and %d" % (PAGE_LIMIT_MIN, PAGE_LIMIT_MAX))
    if raw_offset is not None:
        offset = _query_int("offset", raw_offset)
        if offset < 0:
            bad("offset", "may not be negative")
    return limit, offset


def _query_int(name, raw):
    try:
        return int(raw)
    except (TypeError, ValueError):
        bad(name, "must be an integer")


def query_enum(name, allowed):
    value = request.args.get(name)
    if value is None:
        return None
    if value not in allowed:
        bad(name, "must be one of %s" % ", ".join(allowed))
    return value


def paginate(records, limit, offset):
    total = len(records)
    return records[offset:offset + limit], total
