"""Request-body / query-string shape validation (rejection band 5)."""

from flask import request

from errors import ApiError, bad_request
from store import parse_iso

PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0
PAGINATION_MIN_OFFSET = 0


def body():
    data = request.get_json(silent=True)
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise bad_request("Request body must be a JSON object.")
    return data


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def req_str(data, name, allow_empty=False):
    if name not in data:
        raise bad_request("Field '%s' is required." % name)
    value = data[name]
    if not isinstance(value, str):
        raise bad_request("Field '%s' must be a string." % name)
    if not allow_empty and value.strip() == "":
        raise bad_request("Field '%s' must not be empty." % name)
    return value


def opt_str(data, name, allow_empty=True):
    if name not in data or data[name] is None:
        return None
    return req_str(data, name, allow_empty=allow_empty)


def req_int(data, name, minimum=None, maximum=None):
    if name not in data:
        raise bad_request("Field '%s' is required." % name)
    value = data[name]
    if not _is_int(value):
        raise bad_request("Field '%s' must be an integer." % name)
    if minimum is not None and value < minimum:
        raise bad_request("Field '%s' must be >= %d." % (name, minimum))
    if maximum is not None and value > maximum:
        raise bad_request("Field '%s' must be <= %d." % (name, maximum))
    return value


def opt_int(data, name, minimum=None, maximum=None, allow_null=True):
    if name not in data:
        return None
    if data[name] is None:
        if allow_null:
            return None
        raise bad_request("Field '%s' must not be null." % name)
    return req_int(data, name, minimum=minimum, maximum=maximum)


def req_enum(data, name, choices):
    if name not in data:
        raise bad_request("Field '%s' is required." % name)
    value = data[name]
    if value not in choices:
        raise bad_request(
            "Field '%s' must be one of %s." % (name, ", ".join(str(c) for c in choices))
        )
    return value


def req_int_enum(data, name, choices):
    if name not in data:
        raise bad_request("Field '%s' is required." % name)
    value = data[name]
    if not _is_int(value) or value not in choices:
        raise bad_request(
            "Field '%s' must be one of %s." % (name, ", ".join(str(c) for c in choices))
        )
    return value


def req_datetime(data, name):
    """Returns (raw_string, datetime)."""
    if name not in data:
        raise bad_request("Field '%s' is required." % name)
    raw = data[name]
    if not isinstance(raw, str):
        raise bad_request("Field '%s' must be an ISO 8601 timestamp string." % name)
    parsed = parse_iso(raw)
    if parsed is None:
        raise bad_request("Field '%s' must be a valid ISO 8601 timestamp." % name)
    return raw, parsed


def req_str_array(data, name):
    if name not in data:
        raise bad_request("Field '%s' is required." % name)
    value = data[name]
    if not isinstance(value, list):
        raise bad_request("Field '%s' must be an array." % name)
    for element in value:
        if not isinstance(element, str) or element.strip() == "":
            raise bad_request("Every element of '%s' must be a non-empty string." % name)
    return value


def pagination():
    limit = PAGINATION_DEFAULT_LIMIT
    offset = PAGINATION_DEFAULT_OFFSET
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise bad_request("Query parameter 'limit' must be an integer.")
        if limit < PAGINATION_MIN_LIMIT or limit > PAGINATION_MAX_LIMIT:
            raise bad_request("Query parameter 'limit' must be between 1 and 100.")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise bad_request("Query parameter 'offset' must be an integer.")
        if offset < PAGINATION_MIN_OFFSET:
            raise bad_request("Query parameter 'offset' must be >= 0.")
    return limit, offset


def paginate(records, limit, offset):
    total = len(records)
    return records[offset: offset + limit], total


def query_filter(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    return value


def query_int_filter(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        raise ApiError("ERR_INVALID_REQUEST", "Query parameter '%s' must be an integer." % name)
