"""Request-shape validation (validation priority 4 -> ERR_INVALID_REQUEST)."""
from flask import request

from errors import fail
from util import parse_dt

_MISSING = object()


def body():
    """The JSON request body as a dict; an absent/empty body is an empty dict."""
    raw = request.get_data(cache=True)
    if raw is None or len(raw.strip()) == 0:
        return {}
    parsed = request.get_json(force=True, silent=True)
    if parsed is None:
        fail("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    if not isinstance(parsed, dict):
        fail("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return parsed


def _present(data, name):
    return name in data and data[name] is not None


def req_present(data, name):
    if not _present(data, name):
        fail("ERR_INVALID_REQUEST", "Field '%s' is required." % name)


def string_field(data, name, required=True, non_empty=True, max_len=None,
                 upper_case=False, default=None):
    if not _present(data, name):
        if required:
            fail("ERR_INVALID_REQUEST", "Field '%s' is required." % name)
        return default
    value = data[name]
    if not isinstance(value, str):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a string." % name)
    if non_empty and value.strip() == "":
        fail("ERR_INVALID_REQUEST", "Field '%s' must be non-empty." % name)
    if max_len is not None and len(value) > max_len:
        fail("ERR_INVALID_REQUEST", "Field '%s' exceeds %d characters." % (name, max_len))
    if upper_case and value != value.upper():
        fail("ERR_INVALID_REQUEST", "Field '%s' must be upper-case." % name)
    return value


def int_field(data, name, required=True, minimum=None, maximum=None, default=None):
    if not _present(data, name):
        if required:
            fail("ERR_INVALID_REQUEST", "Field '%s' is required." % name)
        return default
    value = data[name]
    if isinstance(value, bool) or not isinstance(value, int):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be an integer." % name)
    if minimum is not None and value < minimum:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be >= %d." % (name, minimum))
    if maximum is not None and value > maximum:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be <= %d." % (name, maximum))
    return value


def number_field(data, name, required=True, minimum=None, maximum=None, default=None):
    if not _present(data, name):
        if required:
            fail("ERR_INVALID_REQUEST", "Field '%s' is required." % name)
        return default
    value = data[name]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a number." % name)
    if minimum is not None and value < minimum:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be >= %s." % (name, minimum))
    if maximum is not None and value > maximum:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be <= %s." % (name, maximum))
    return value


def bool_field(data, name, required=False, default=None):
    if not _present(data, name):
        if required:
            fail("ERR_INVALID_REQUEST", "Field '%s' is required." % name)
        return default
    value = data[name]
    if not isinstance(value, bool):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a boolean." % name)
    return value


def enum_field(data, name, allowed, required=True, default=None):
    if not _present(data, name):
        if required:
            fail("ERR_INVALID_REQUEST", "Field '%s' is required." % name)
        return default
    value = data[name]
    if not isinstance(value, str) or value not in allowed:
        fail("ERR_INVALID_REQUEST",
             "Field '%s' must be one of %s." % (name, ", ".join(sorted(allowed))))
    return value


def dt_field(data, name, required=True, default=None):
    if not _present(data, name):
        if required:
            fail("ERR_INVALID_REQUEST", "Field '%s' is required." % name)
        return default
    value = data[name]
    if not isinstance(value, str):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be an ISO-8601 string." % name)
    parsed = parse_dt(value)
    if parsed is None:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be an ISO-8601 instant." % name)
    return parsed


def id_field(data, name, required=True, default=None):
    if not _present(data, name):
        if required:
            fail("ERR_INVALID_REQUEST", "Field '%s' is required." % name)
        return default
    value = data[name]
    if not isinstance(value, str) or value.strip() == "":
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a non-empty string identifier." % name)
    return value


def pagination():
    """limit (default 10, 1..100) and offset (default 0, >= 0) from the query string."""
    limit = 10
    offset = 0
    raw_limit = request.args.get("limit")
    if raw_limit is not None and raw_limit != "":
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            fail("ERR_INVALID_REQUEST", "Query parameter 'limit' must be an integer.")
        if limit < 1 or limit > 100:
            fail("ERR_INVALID_REQUEST", "Query parameter 'limit' must be between 1 and 100.")
    raw_offset = request.args.get("offset")
    if raw_offset is not None and raw_offset != "":
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            fail("ERR_INVALID_REQUEST", "Query parameter 'offset' must be an integer.")
        if offset < 0:
            fail("ERR_INVALID_REQUEST", "Query parameter 'offset' must not be negative.")
    return limit, offset


def paginate(rows, serializer):
    limit, offset = pagination()
    total = len(rows)
    page = rows[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(page) < total,
    }
    return [serializer(row) for row in page], meta


def query_filter(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    return value
