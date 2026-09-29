"""Rank 3 of the rejection ladder: body and query shape (ERR_INVALID_REQUEST)."""
from flask import request

import clock
import errors
from errors import fail

PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0


def bad(message):
    fail(errors.ERR_INVALID_REQUEST, message)


def body():
    if not request.data:
        return {}
    payload = request.get_json(silent=True)
    if payload is None:
        bad("Request body is not valid JSON.")
    if not isinstance(payload, dict):
        bad("Request body must be a JSON object.")
    return payload


def _present(data, field):
    return field in data and data[field] is not None


def req_str(data, field):
    if not _present(data, field):
        bad("Field '%s' is required." % field)
    value = data[field]
    if not isinstance(value, str) or not value.strip():
        bad("Field '%s' must be a non-empty string." % field)
    return value


def opt_str(data, field, default=None):
    if not _present(data, field):
        return default
    value = data[field]
    if not isinstance(value, str):
        bad("Field '%s' must be a string." % field)
    return value


def _check_int(field, value, minimum=None, maximum=None):
    if isinstance(value, bool) or not isinstance(value, int):
        bad("Field '%s' must be an integer." % field)
    if minimum is not None and value < minimum:
        bad("Field '%s' must be >= %s." % (field, minimum))
    if maximum is not None and value > maximum:
        bad("Field '%s' must be <= %s." % (field, maximum))
    return value


def req_int(data, field, minimum=None, maximum=None):
    if not _present(data, field):
        bad("Field '%s' is required." % field)
    return _check_int(field, data[field], minimum, maximum)


def opt_int(data, field, minimum=None, maximum=None, default=None):
    if not _present(data, field):
        return default
    return _check_int(field, data[field], minimum, maximum)


def req_enum(data, field, allowed):
    value = req_str(data, field)
    if value not in allowed:
        bad("Field '%s' must be one of %s." % (field, ", ".join(sorted(allowed))))
    return value


def opt_enum(data, field, allowed, default=None):
    if not _present(data, field):
        return default
    value = data[field]
    if not isinstance(value, str) or value not in allowed:
        bad("Field '%s' must be one of %s." % (field, ", ".join(sorted(allowed))))
    return value


def opt_bool(data, field, default=None):
    if not _present(data, field):
        return default
    value = data[field]
    if not isinstance(value, bool):
        bad("Field '%s' must be a boolean." % field)
    return value


def req_bool(data, field):
    if not _present(data, field):
        bad("Field '%s' is required." % field)
    value = data[field]
    if not isinstance(value, bool):
        bad("Field '%s' must be a boolean." % field)
    return value


def req_datetime(data, field):
    value = req_str(data, field)
    try:
        return clock.parse(value)
    except (ValueError, TypeError):
        bad("Field '%s' must be an ISO 8601 instant." % field)


def req_str_list(data, field):
    if not _present(data, field):
        bad("Field '%s' is required." % field)
    value = data[field]
    if not isinstance(value, list) or len(value) == 0:
        bad("Field '%s' must be a non-empty array." % field)
    for entry in value:
        if not isinstance(entry, str) or not entry.strip():
            bad("Field '%s' must contain non-empty strings." % field)
    return value


def req_lines(data):
    if not _present(data, "lines"):
        bad("Field 'lines' is required.")
    value = data["lines"]
    if not isinstance(value, list) or len(value) == 0:
        bad("Field 'lines' must be a non-empty array.")
    parsed = []
    for entry in value:
        if not isinstance(entry, dict):
            bad("Each entry of 'lines' must be an object.")
        parsed.append({
            "sku": req_str(entry, "sku"),
            "quantity": req_int(entry, "quantity", 1, 50),
        })
    return parsed


# --- query parameters -------------------------------------------------------

def pagination():
    args = request.args
    limit = PAGINATION_DEFAULT_LIMIT
    offset = PAGINATION_DEFAULT_OFFSET
    if "limit" in args:
        raw = args.get("limit")
        try:
            limit = int(raw)
        except (TypeError, ValueError):
            bad("Query parameter 'limit' must be an integer.")
        if limit < PAGINATION_MIN_LIMIT or limit > PAGINATION_MAX_LIMIT:
            bad("Query parameter 'limit' must be between 1 and 100.")
    if "offset" in args:
        raw = args.get("offset")
        try:
            offset = int(raw)
        except (TypeError, ValueError):
            bad("Query parameter 'offset' must be an integer.")
        if offset < 0:
            bad("Query parameter 'offset' must be >= 0.")
    return limit, offset


def query_str(name):
    value = request.args.get(name)
    if value is None:
        return None
    if not value.strip():
        bad("Query parameter '%s' must be a non-empty string." % name)
    return value


def query_enum(name, allowed):
    value = request.args.get(name)
    if value is None:
        return None
    if value not in allowed:
        bad("Query parameter '%s' must be one of %s." % (name, ", ".join(sorted(allowed))))
    return value


def query_int(name, minimum=None, maximum=None):
    value = request.args.get(name)
    if value is None:
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        bad("Query parameter '%s' must be an integer." % name)
    if minimum is not None and parsed < minimum:
        bad("Query parameter '%s' must be >= %s." % (name, minimum))
    if maximum is not None and parsed > maximum:
        bad("Query parameter '%s' must be <= %s." % (name, maximum))
    return parsed
