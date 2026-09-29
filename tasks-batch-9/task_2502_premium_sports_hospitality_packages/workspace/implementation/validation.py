"""Request-shape validation: rejection ladder step 4 (PRD 2.7 / 2.3)."""
from flask import request

from errors import ERR_INVALID_REQUEST, fail
from util import dec, parse_ts

MISSING = object()


def bad(message):
    fail(ERR_INVALID_REQUEST, message)


def body():
    """The parsed JSON body, or {} when the caller sent nothing at all."""
    raw = request.get_data(cache=True)
    if raw is None or len(raw.strip()) == 0:
        return {}
    parsed = request.get_json(silent=True, force=True)
    if parsed is None:
        bad("Request body is not valid JSON.")
    if not isinstance(parsed, dict):
        bad("Request body must be a JSON object.")
    return parsed


def _present(data, key):
    return key in data and data[key] is not None


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _is_num(value):
    return (isinstance(value, int) or isinstance(value, float)) and not isinstance(value, bool)


# --- typed field readers ----------------------------------------------------


def req_string(data, key):
    if not _present(data, key):
        bad("Field `%s` is required." % key)
    value = data[key]
    if not isinstance(value, str) or not value.strip():
        bad("Field `%s` must be a non-empty string." % key)
    return value


def opt_string(data, key, default=None):
    if not _present(data, key):
        return default
    return req_string(data, key)


def req_int(data, key, minimum=None, maximum=None):
    if not _present(data, key):
        bad("Field `%s` is required." % key)
    value = data[key]
    if not _is_int(value):
        bad("Field `%s` must be an integer." % key)
    if minimum is not None and value < minimum:
        bad("Field `%s` must be >= %s." % (key, minimum))
    if maximum is not None and value > maximum:
        bad("Field `%s` must be <= %s." % (key, maximum))
    return value


def opt_int(data, key, default=0, minimum=None, maximum=None):
    if not _present(data, key):
        return default
    return req_int(data, key, minimum=minimum, maximum=maximum)


def req_number(data, key, minimum=None, maximum=None):
    if not _present(data, key):
        bad("Field `%s` is required." % key)
    value = data[key]
    if not _is_num(value):
        bad("Field `%s` must be a number." % key)
    number = dec(value)
    if minimum is not None and number < dec(minimum):
        bad("Field `%s` must be >= %s." % (key, minimum))
    if maximum is not None and number > dec(maximum):
        bad("Field `%s` must be <= %s." % (key, maximum))
    return number


def opt_number(data, key, default, minimum=None, maximum=None):
    if not _present(data, key):
        return dec(default)
    return req_number(data, key, minimum=minimum, maximum=maximum)


def req_bool(data, key):
    if not _present(data, key):
        bad("Field `%s` is required." % key)
    value = data[key]
    if not isinstance(value, bool):
        bad("Field `%s` must be a boolean." % key)
    return value


def opt_bool(data, key, default=False):
    if not _present(data, key):
        return default
    return req_bool(data, key)


def req_enum(data, key, allowed):
    value = req_string(data, key)
    if value not in allowed:
        bad("Field `%s` must be one of %s." % (key, ", ".join(allowed)))
    return value


def opt_enum(data, key, allowed, default=None):
    if not _present(data, key):
        return default
    return req_enum(data, key, allowed)


def req_datetime(data, key):
    if not _present(data, key):
        bad("Field `%s` is required." % key)
    value = data[key]
    try:
        return parse_ts(value)
    except (ValueError, TypeError):
        bad("Field `%s` must be an ISO 8601 UTC timestamp." % key)


def opt_datetime(data, key, default=None):
    if not _present(data, key):
        return default
    return req_datetime(data, key)


def req_string_array(data, key, unique=False, non_empty=False):
    if not _present(data, key):
        bad("Field `%s` is required." % key)
    value = data[key]
    if not isinstance(value, list):
        bad("Field `%s` must be an array of strings." % key)
    for item in value:
        if not isinstance(item, str) or not item.strip():
            bad("Field `%s` must contain only non-empty strings." % key)
    if non_empty and len(value) == 0:
        bad("Field `%s` must not be empty." % key)
    if unique and len(set(value)) != len(value):
        bad("Field `%s` must contain unique values." % key)
    return list(value)


def req_id(data, key):
    """A foreign key: shape-checked here, resolved at ladder step 5."""
    return req_string(data, key)


# --- query parameters -------------------------------------------------------


def pagination():
    limit = 10
    offset = 0
    raw_limit = request.args.get("limit")
    if raw_limit is not None and raw_limit != "":
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            bad("Query parameter `limit` must be an integer between 1 and 100.")
        if limit < 1 or limit > 100:
            bad("Query parameter `limit` must be between 1 and 100 inclusive.")
    raw_offset = request.args.get("offset")
    if raw_offset is not None and raw_offset != "":
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            bad("Query parameter `offset` must be a non-negative integer.")
        if offset < 0:
            bad("Query parameter `offset` must be >= 0.")
    return limit, offset


def query_filter(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    return value


def paginate(records, limit, offset):
    return records[offset : offset + limit]
