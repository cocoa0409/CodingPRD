"""Request body and query-parameter validation (PRD Sections 2.3 and 2.10 rule 7)."""

from datetime import date

from flask import request

from errors import ApiError

_MISSING = object()


def body():
    """Return the JSON body as a dict; a non-object body is ERR_INVALID_REQUEST."""
    if not request.data:
        return {}
    try:
        payload = request.get_json(force=True, silent=False)
    except Exception:
        raise ApiError("ERR_INVALID_REQUEST", "Request body is not valid JSON.")
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        raise ApiError("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return payload


def _present(data, key):
    return key in data and data[key] is not None


def bad(field, why):
    raise ApiError("ERR_INVALID_REQUEST", "Field '%s' %s." % (field, why))


# --------------------------------------------------------------------------
# scalar readers
# --------------------------------------------------------------------------
def req_string(data, key, allow_empty=False):
    if not _present(data, key):
        bad(key, "is required")
    value = data[key]
    if not isinstance(value, str):
        bad(key, "must be a string")
    if not allow_empty and value.strip() == "":
        bad(key, "must be a non-empty string")
    return value


def opt_string(data, key, default=None, allow_empty=True):
    if key not in data or data[key] is None:
        return default
    value = data[key]
    if not isinstance(value, str):
        bad(key, "must be a string")
    if not allow_empty and value.strip() == "":
        bad(key, "must be a non-empty string")
    return value


def req_id(data, key):
    """Read a foreign-key identifier before existence resolution."""
    if not _present(data, key):
        bad(key, "is required")
    value = data[key]
    if not isinstance(value, str) or value.strip() == "":
        bad(key, "must be a non-empty string identifier")
    return value


def opt_id(data, key):
    if key not in data or data[key] is None:
        return None
    value = data[key]
    if not isinstance(value, str) or value.strip() == "":
        bad(key, "must be a non-empty string identifier")
    return value


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def req_int(data, key, minimum=None, maximum=None):
    if not _present(data, key):
        bad(key, "is required")
    value = data[key]
    if not _is_int(value):
        bad(key, "must be an integer")
    if minimum is not None and value < minimum:
        bad(key, "must be at least %s" % minimum)
    if maximum is not None and value > maximum:
        bad(key, "must be at most %s" % maximum)
    return value


def opt_int(data, key, default=None, minimum=None, maximum=None):
    if key not in data or data[key] is None:
        return default
    return req_int(data, key, minimum=minimum, maximum=maximum)


def req_number(data, key, minimum=None, maximum=None):
    if not _present(data, key):
        bad(key, "is required")
    value = data[key]
    if not _is_number(value):
        bad(key, "must be a number")
    if minimum is not None and value < minimum:
        bad(key, "must be at least %s" % minimum)
    if maximum is not None and value > maximum:
        bad(key, "must be at most %s" % maximum)
    return value


def req_bool(data, key):
    if not _present(data, key):
        bad(key, "is required")
    value = data[key]
    if not isinstance(value, bool):
        bad(key, "must be a boolean")
    return value


def opt_bool(data, key, default=None):
    if key not in data or data[key] is None:
        return default
    return req_bool(data, key)


def req_enum(data, key, members):
    value = req_string(data, key)
    if value not in members:
        bad(key, "must be one of %s" % ", ".join(members))
    return value


def opt_enum(data, key, members, default=None):
    if key not in data or data[key] is None:
        return default
    return req_enum(data, key, members)


def req_string_array(data, key, non_empty=True):
    if not _present(data, key):
        bad(key, "is required")
    value = data[key]
    if not isinstance(value, list):
        bad(key, "must be an array of strings")
    for element in value:
        if not isinstance(element, str) or element.strip() == "":
            bad(key, "must contain only non-empty strings")
    if non_empty and len(value) == 0:
        bad(key, "must be a non-empty array")
    return list(value)


def opt_string_array(data, key, default=None):
    if key not in data or data[key] is None:
        return list(default) if default is not None else None
    return req_string_array(data, key, non_empty=False)


def req_date(data, key):
    value = req_string(data, key)
    parsed = parse_date(value)
    if parsed is None:
        bad(key, "must be a calendar date in the form YYYY-MM-DD")
    return value


def parse_date(text):
    if not isinstance(text, str) or len(text) != 10:
        return None
    try:
        year, month, day = text.split("-")
        return date(int(year), int(month), int(day))
    except (ValueError, TypeError):
        return None


# --------------------------------------------------------------------------
# pagination and filters (PRD Section 2.3)
# --------------------------------------------------------------------------
def pagination():
    limit = 10
    offset = 0
    raw_limit = request.args.get("limit")
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", "Query parameter 'limit' must be an integer.")
        if str(raw_limit).strip() != str(limit):
            raise ApiError("ERR_INVALID_REQUEST", "Query parameter 'limit' must be an integer.")
        if limit < 1 or limit > 100:
            raise ApiError("ERR_INVALID_REQUEST", "Query parameter 'limit' must be between 1 and 100.")
    raw_offset = request.args.get("offset")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", "Query parameter 'offset' must be an integer.")
        if str(raw_offset).strip() != str(offset):
            raise ApiError("ERR_INVALID_REQUEST", "Query parameter 'offset' must be an integer.")
        if offset < 0:
            raise ApiError("ERR_INVALID_REQUEST", "Query parameter 'offset' must be at least 0.")
    return limit, offset


def query_int(name):
    raw = request.args.get(name)
    if raw is None:
        return None
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise ApiError("ERR_INVALID_REQUEST", "Query parameter '%s' must be an integer." % name)
    if str(raw).strip() != str(value):
        raise ApiError("ERR_INVALID_REQUEST", "Query parameter '%s' must be an integer." % name)
    return value


def query_str(name):
    raw = request.args.get(name)
    if raw is None:
        return None
    return raw


def window(rows, limit, offset):
    return rows[offset : offset + limit]
