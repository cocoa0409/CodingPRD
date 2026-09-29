"""Request body / query-string schema validation (ladder position 6)."""

from flask import request

import store
from errors import fail


def body():
    """The JSON body as a dict; an absent body is an empty dict."""
    raw = request.get_data(cache=True, as_text=True)
    if raw is None or not raw.strip():
        return {}
    parsed = request.get_json(silent=True)
    if parsed is None:
        fail("ERR_VALIDATION", "Request body must be a JSON object.")
    if not isinstance(parsed, dict):
        fail("ERR_VALIDATION", "Request body must be a JSON object.")
    return parsed


def _bad(name, why):
    fail("ERR_VALIDATION", "Field '%s' %s." % (name, why))


def present(data, name):
    return name in data and data[name] is not None


def req_str(data, name):
    if not present(data, name):
        _bad(name, "is required")
    value = data[name]
    if not isinstance(value, str) or not value.strip():
        _bad(name, "must be a non-empty string")
    return value


def opt_str(data, name, default=None):
    if not present(data, name):
        return default
    return req_str(data, name)


def req_id(data, name):
    """A foreign key: must be a non-empty string."""
    return req_str(data, name)


def req_int(data, name, minimum=None, maximum=None):
    if not present(data, name):
        _bad(name, "is required")
    return _as_int(data[name], name, minimum, maximum)


def opt_int(data, name, minimum=None, maximum=None, default=None):
    if not present(data, name):
        return default
    return _as_int(data[name], name, minimum, maximum)


def _as_int(value, name, minimum, maximum):
    if isinstance(value, bool) or not isinstance(value, int):
        _bad(name, "must be an integer")
    if minimum is not None and value < minimum:
        _bad(name, "must be at least %s" % minimum)
    if maximum is not None and value > maximum:
        _bad(name, "must be at most %s" % maximum)
    return value


def req_num(data, name, minimum=None, maximum=None):
    if not present(data, name):
        _bad(name, "is required")
    return _as_num(data[name], name, minimum, maximum)


def opt_num(data, name, minimum=None, maximum=None, default=None):
    if not present(data, name):
        return default
    return _as_num(data[name], name, minimum, maximum)


def _as_num(value, name, minimum, maximum):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _bad(name, "must be a number")
    if minimum is not None and value < minimum:
        _bad(name, "must be at least %s" % minimum)
    if maximum is not None and value > maximum:
        _bad(name, "must be at most %s" % maximum)
    return value


def req_bool(data, name):
    if not present(data, name):
        _bad(name, "is required")
    value = data[name]
    if not isinstance(value, bool):
        _bad(name, "must be a boolean")
    return value


def opt_bool(data, name, default=None):
    if not present(data, name):
        return default
    return req_bool(data, name)


def req_enum(data, name, allowed):
    value = req_str(data, name)
    if value not in allowed:
        _bad(name, "must be one of %s" % ", ".join(sorted(allowed)))
    return value


def opt_enum(data, name, allowed, default=None):
    if not present(data, name):
        return default
    return req_enum(data, name, allowed)


def req_dt(data, name):
    value = req_str(data, name)
    parsed = store.parse_dt(value)
    if parsed is None:
        _bad(name, "must be an ISO-8601 timestamp")
    return parsed


def req_id_list(data, name):
    if not present(data, name):
        _bad(name, "is required")
    value = data[name]
    if not isinstance(value, list):
        _bad(name, "must be an array")
    for entry in value:
        if not isinstance(entry, str) or not entry.strip():
            _bad(name, "must contain only non-empty strings")
    return list(value)


def opt_id_list(data, name):
    if not present(data, name):
        return None
    return req_id_list(data, name)


def raw_fk(data, name):
    """The raw value of a body foreign key, for the pre-schema existence pass."""
    value = data.get(name)
    if isinstance(value, str) and value.strip():
        return value
    return None


def pagination():
    """limit / offset with the PRD 2.3 defaults and bounds."""
    limit = _query_int("limit", 10, 1, 100)
    offset = _query_int("offset", 0, 0, None)
    return limit, offset


def _query_int(name, default, minimum, maximum):
    if name not in request.args:
        return default
    raw = request.args.get(name)
    if raw is None or raw.strip() == "":
        fail("ERR_VALIDATION", "Query parameter '%s' must be an integer." % name)
    try:
        value = int(raw.strip(), 10)
    except ValueError:
        fail("ERR_VALIDATION", "Query parameter '%s' must be an integer." % name)
    if minimum is not None and value < minimum:
        fail("ERR_VALIDATION", "Query parameter '%s' must be at least %s." % (name, minimum))
    if maximum is not None and value > maximum:
        fail("ERR_VALIDATION", "Query parameter '%s' must be at most %s." % (name, maximum))
    return value


def q(name):
    value = request.args.get(name)
    if value is None:
        return None
    value = value.strip()
    return value or None


def window(rows, limit, offset):
    return rows[offset:offset + limit]


def lookup(collection, row_id, error_id):
    """Path or body existence check."""
    if not isinstance(row_id, str):
        fail(error_id)
    row = collection.get(row_id)
    if row is None:
        fail(error_id)
    return row
