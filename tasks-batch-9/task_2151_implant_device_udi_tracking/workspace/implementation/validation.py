"""Ladder step 3 — request shape validation (ERR_INVALID_REQUEST, 400)."""
from flask import request

from errors import ApiError
from store import parse_date, parse_iso

INVALID = "ERR_INVALID_REQUEST"


def bad(msg):
    return ApiError(INVALID, msg)


def body():
    data = request.get_json(silent=True)
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise bad("Request body must be a JSON object.")
    return data


def present(data, name):
    return name in data and data[name] is not None


def req_str(data, name):
    if not present(data, name):
        raise bad("Field '%s' is required." % name)
    value = data[name]
    if not isinstance(value, str) or not value.strip():
        raise bad("Field '%s' must be a non-empty string." % name)
    return value


def opt_str(data, name, default=None):
    if not present(data, name):
        return default
    value = data[name]
    if not isinstance(value, str) or not value.strip():
        raise bad("Field '%s' must be a non-empty string when supplied." % name)
    return value


def req_int(data, name, minimum=None, maximum=None):
    if not present(data, name):
        raise bad("Field '%s' is required." % name)
    return _as_int(data[name], name, minimum, maximum)


def opt_int(data, name, default=None, minimum=None, maximum=None):
    if not present(data, name):
        return default
    return _as_int(data[name], name, minimum, maximum)


def _as_int(value, name, minimum, maximum):
    if isinstance(value, bool) or not isinstance(value, int):
        raise bad("Field '%s' must be an integer." % name)
    if minimum is not None and value < minimum:
        raise bad("Field '%s' must be at least %d." % (name, minimum))
    if maximum is not None and value > maximum:
        raise bad("Field '%s' must be at most %d." % (name, maximum))
    return value


def req_enum(data, name, allowed):
    value = req_str(data, name)
    if value not in allowed:
        raise bad("Field '%s' must be one of %s." % (name, ", ".join(sorted(allowed))))
    return value


def opt_enum(data, name, allowed, default=None):
    if not present(data, name):
        return default
    value = data[name]
    if not isinstance(value, str) or value not in allowed:
        raise bad("Field '%s' must be one of %s." % (name, ", ".join(sorted(allowed))))
    return value


def req_bool(data, name, default=None):
    if not present(data, name):
        return default
    value = data[name]
    if not isinstance(value, bool):
        raise bad("Field '%s' must be a boolean." % name)
    return value


def req_dt(data, name):
    raw = req_str(data, name)
    parsed = parse_iso(raw)
    if parsed is None:
        raise bad("Field '%s' must be an ISO 8601 instant." % name)
    return parsed


def req_date_str(data, name):
    raw = req_str(data, name)
    if parse_date(raw) is None:
        raise bad("Field '%s' must be a YYYY-MM-DD calendar date." % name)
    return raw.strip()


def req_id(data, name):
    """A foreign-key reference: must be present and a non-empty string."""
    return req_str(data, name)


def opt_id(data, name):
    return opt_str(data, name)


def req_str_array(data, name):
    if not present(data, name):
        raise bad("Field '%s' is required." % name)
    value = data[name]
    if not isinstance(value, list) or not value:
        raise bad("Field '%s' must be a non-empty array." % name)
    for member in value:
        if not isinstance(member, str) or not member.strip():
            raise bad("Field '%s' must contain non-empty strings." % name)
    return value


def opt_str_array(data, name):
    if not present(data, name):
        return None
    return req_str_array(data, name)


def forbid(data, name, reason):
    if name in data and data[name] is not None:
        raise bad("Field '%s' must be omitted %s." % (name, reason))


def pagination():
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args and args.get("limit") != "":
        raw = args.get("limit")
        try:
            limit = int(raw)
        except (TypeError, ValueError):
            raise bad("Query parameter 'limit' must be an integer.")
        if limit < 1 or limit > 100:
            raise bad("Query parameter 'limit' must be between 1 and 100.")
    if "offset" in args and args.get("offset") != "":
        raw = args.get("offset")
        try:
            offset = int(raw)
        except (TypeError, ValueError):
            raise bad("Query parameter 'offset' must be an integer.")
        if offset < 0:
            raise bad("Query parameter 'offset' must be at least 0.")
    return limit, offset


def filter_value(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    return value


def filter_enum(name, allowed):
    value = filter_value(name)
    if value is None:
        return None
    if value not in allowed:
        raise bad("Query parameter '%s' must be one of %s." % (name, ", ".join(sorted(allowed))))
    return value


def apply_page(rows, limit, offset):
    total = len(rows)
    return rows[offset:offset + limit], total


def opt_bool_default(data, name, default):
    if not present(data, name):
        return default
    value = data[name]
    if not isinstance(value, bool):
        raise bad("Field '%s' must be a boolean." % name)
    return value
