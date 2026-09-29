"""Request-shape validation helpers (PRD section 2.9 band 6, section 2.3)."""

from flask import request

from errors import fail
from store import parse_dt

PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0

_MISSING = object()


def body():
    """Parsed JSON body; an absent or empty body is treated as {}."""
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


def ref_id(data, name):
    """Value of a body foreign key when it is usable for lookup, else None."""
    value = data.get(name)
    if isinstance(value, str) and value.strip():
        return value
    return None


def req_str(data, name, min_len=1, max_len=None):
    if not _present(data, name):
        fail("ERR_INVALID_REQUEST", "Field '%s' is required." % name)
    value = data[name]
    if not isinstance(value, str):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a string." % name)
    if len(value) < min_len:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be at least %d characters." % (name, min_len))
    if max_len is not None and len(value) > max_len:
        fail("ERR_INVALID_REQUEST", "Field '%s' may not exceed %d characters." % (name, max_len))
    return value


def opt_str(data, name, default=None, min_len=0, max_len=None, allow_null=True):
    if name not in data:
        return default
    value = data[name]
    if value is None:
        if allow_null:
            return None
        fail("ERR_INVALID_REQUEST", "Field '%s' may not be null." % name)
    if not isinstance(value, str):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a string." % name)
    if len(value) < min_len:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be at least %d characters." % (name, min_len))
    if max_len is not None and len(value) > max_len:
        fail("ERR_INVALID_REQUEST", "Field '%s' may not exceed %d characters." % (name, max_len))
    return value


def _check_int(name, value, minimum):
    if isinstance(value, bool) or not isinstance(value, int):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be an integer." % name)
    if minimum is not None and value < minimum:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be at least %d." % (name, minimum))
    return value


def req_int(data, name, minimum=None):
    if not _present(data, name):
        fail("ERR_INVALID_REQUEST", "Field '%s' is required." % name)
    return _check_int(name, data[name], minimum)


def opt_int(data, name, default=None, minimum=None):
    if not _present(data, name):
        if name in data and data[name] is None:
            return None
        return default
    return _check_int(name, data[name], minimum)


def _check_num(name, value, minimum, maximum):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a number." % name)
    if minimum is not None and value < minimum:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be at least %s." % (name, minimum))
    if maximum is not None and value > maximum:
        fail("ERR_INVALID_REQUEST", "Field '%s' may not exceed %s." % (name, maximum))
    return value


def req_num(data, name, minimum=None, maximum=None):
    if not _present(data, name):
        fail("ERR_INVALID_REQUEST", "Field '%s' is required." % name)
    return _check_num(name, data[name], minimum, maximum)


def opt_num(data, name, default=None, minimum=None, maximum=None):
    if not _present(data, name):
        return default
    return _check_num(name, data[name], minimum, maximum)


def req_bool(data, name):
    if not _present(data, name):
        fail("ERR_INVALID_REQUEST", "Field '%s' is required." % name)
    if not isinstance(data[name], bool):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a boolean." % name)
    return data[name]


def opt_bool(data, name, default=None):
    if not _present(data, name):
        return default
    if not isinstance(data[name], bool):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a boolean." % name)
    return data[name]


def req_enum(data, name, allowed):
    value = req_str(data, name)
    if value not in allowed:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be one of %s." % (name, ", ".join(allowed)))
    return value


def opt_enum(data, name, allowed, default=None):
    if not _present(data, name):
        return default
    value = data[name]
    if not isinstance(value, str) or value not in allowed:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be one of %s." % (name, ", ".join(allowed)))
    return value


def req_dt(data, name):
    if not _present(data, name):
        fail("ERR_INVALID_REQUEST", "Field '%s' is required." % name)
    parsed = parse_dt(data[name])
    if parsed is None:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be an ISO 8601 instant." % name)
    return parsed


def opt_dt(data, name, default=None):
    if not _present(data, name):
        return default
    parsed = parse_dt(data[name])
    if parsed is None:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be an ISO 8601 instant." % name)
    return parsed


def req_ref(data, name):
    """A required foreign-key field: must be present and a non-empty string."""
    return req_str(data, name)


def opt_ref(data, name):
    if name not in data or data[name] is None:
        return None
    value = data[name]
    if not isinstance(value, str) or not value.strip():
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a string identifier." % name)
    return value


def strictly_after(later, earlier, later_name, earlier_name):
    if not later > earlier:
        fail("ERR_INVALID_REQUEST",
             "Field '%s' must be strictly after '%s'." % (later_name, earlier_name))


# --------------------------------------------------------------------------
# query parameters
# --------------------------------------------------------------------------

def pagination():
    limit = PAGINATION_DEFAULT_LIMIT
    offset = PAGINATION_DEFAULT_OFFSET
    raw_limit = request.args.get("limit")
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            fail("ERR_INVALID_REQUEST", "Query parameter 'limit' must be an integer.")
        if limit < PAGINATION_MIN_LIMIT or limit > PAGINATION_MAX_LIMIT:
            fail("ERR_INVALID_REQUEST", "Query parameter 'limit' must be between 1 and 100.")
    raw_offset = request.args.get("offset")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            fail("ERR_INVALID_REQUEST", "Query parameter 'offset' must be an integer.")
        if offset < 0:
            fail("ERR_INVALID_REQUEST", "Query parameter 'offset' may not be negative.")
    return limit, offset


def query_filter(name, allowed=None):
    value = request.args.get(name)
    if value is None:
        return None
    if allowed is not None and value not in allowed:
        fail("ERR_INVALID_REQUEST",
             "Query parameter '%s' must be one of %s." % (name, ", ".join(allowed)))
    return value


def paginate(rows, limit, offset):
    return rows[offset:offset + limit]
