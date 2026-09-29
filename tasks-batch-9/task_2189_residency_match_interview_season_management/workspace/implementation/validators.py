"""Request-shape validation (priority 4) and body foreign-key resolution
(priority 3), plus pagination / filter parsing."""

from flask import request

from errors import ApiError
from store import find, parse_iso

MISSING = object()


# ------------------------------------------------------------------ body
def body():
    """The parsed JSON object of the request, or {} when there is no body."""
    raw = request.get_data(cache=True) or b""
    if not raw.strip():
        return {}
    data = request.get_json(silent=True)
    if data is None:
        raise ApiError("ERR_VALIDATION", "Request body is not valid JSON.")
    if not isinstance(data, dict):
        raise ApiError("ERR_VALIDATION", "Request body must be a JSON object.")
    return data


def _bad(field, why):
    raise ApiError("ERR_VALIDATION", "Field '%s' %s." % (field, why))


def present(data, field):
    return field in data and data[field] is not None


# ------------------------------------------------------------------ priority 3
def fk(data, field, collection):
    """Resolve a body foreign key.

    A supplied, string-typed value that names no row is ERR_RESOURCE_NOT_FOUND
    (priority 3).  An absent or non-string value is left for the priority-4
    shape check, so ordering between the two priorities is preserved.
    """
    if not present(data, field):
        return None
    value = data[field]
    if not isinstance(value, str):
        return None
    row = find(collection, value)
    if row is None:
        raise ApiError("ERR_RESOURCE_NOT_FOUND")
    return row


# ------------------------------------------------------------------ priority 4
def req_str(data, field, max_len=None, allow_empty=False):
    if not present(data, field):
        _bad(field, "is required")
    value = data[field]
    if not isinstance(value, str):
        _bad(field, "must be a string")
    if not allow_empty and not value.strip():
        _bad(field, "must be non-empty")
    if max_len is not None and len(value) > max_len:
        _bad(field, "exceeds %d characters" % max_len)
    return value


def opt_str(data, field, default=None, max_len=None, allow_empty=True):
    if not present(data, field):
        return default
    return req_str(data, field, max_len=max_len, allow_empty=allow_empty)


def req_int(data, field, minimum=None, maximum=None):
    if not present(data, field):
        _bad(field, "is required")
    value = data[field]
    if isinstance(value, bool) or not isinstance(value, int):
        _bad(field, "must be an integer")
    if minimum is not None and value < minimum:
        _bad(field, "must be >= %d" % minimum)
    if maximum is not None and value > maximum:
        _bad(field, "must be <= %d" % maximum)
    return value


def opt_int(data, field, default=None, minimum=None, maximum=None):
    if not present(data, field):
        return default
    return req_int(data, field, minimum=minimum, maximum=maximum)


def req_bool(data, field):
    if not present(data, field):
        _bad(field, "is required")
    value = data[field]
    if not isinstance(value, bool):
        _bad(field, "must be a boolean")
    return value


def opt_bool(data, field, default=False):
    if not present(data, field):
        return default
    return req_bool(data, field)


def req_enum(data, field, allowed):
    value = req_str(data, field)
    if value not in allowed:
        _bad(field, "must be one of %s" % ", ".join(allowed))
    return value


def opt_enum(data, field, allowed, default=None):
    if not present(data, field):
        return default
    return req_enum(data, field, allowed)


def req_dt(data, field):
    value = req_str(data, field)
    parsed = parse_iso(value)
    if parsed is None:
        _bad(field, "must be an ISO 8601 instant")
    return parsed


def req_id_list(data, field, default=None):
    """An optional array of resource-id strings."""
    if not present(data, field):
        return list(default or [])
    value = data[field]
    if not isinstance(value, list):
        _bad(field, "must be an array")
    for item in value:
        if not isinstance(item, str) or not item.strip():
            _bad(field, "must be an array of resource ids")
    return value


# ------------------------------------------------------------------ query args
def _query_int(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        raise ApiError("ERR_VALIDATION", "Query parameter '%s' must be an integer." % name)


def pagination():
    limit = _query_int("limit")
    offset = _query_int("offset")
    if limit is None:
        limit = 10
    if offset is None:
        offset = 0
    if limit < 1 or limit > 100:
        raise ApiError("ERR_VALIDATION", "limit must be between 1 and 100.")
    if offset < 0:
        raise ApiError("ERR_VALIDATION", "offset must be 0 or greater.")
    return limit, offset


def q_str(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    return raw


def q_enum(name, allowed):
    raw = q_str(name)
    if raw is None:
        return None
    if raw not in allowed:
        raise ApiError("ERR_VALIDATION", "Query parameter '%s' is not a declared member." % name)
    return raw


def q_bool(name):
    raw = q_str(name)
    if raw is None:
        return None
    lowered = raw.lower()
    if lowered in ("true", "1"):
        return True
    if lowered in ("false", "0"):
        return False
    raise ApiError("ERR_VALIDATION", "Query parameter '%s' must be a boolean." % name)


def q_int(name, minimum=None, maximum=None):
    value = _query_int(name)
    if value is None:
        return None
    if minimum is not None and value < minimum:
        raise ApiError("ERR_VALIDATION", "Query parameter '%s' is out of range." % name)
    if maximum is not None and value > maximum:
        raise ApiError("ERR_VALIDATION", "Query parameter '%s' is out of range." % name)
    return value
