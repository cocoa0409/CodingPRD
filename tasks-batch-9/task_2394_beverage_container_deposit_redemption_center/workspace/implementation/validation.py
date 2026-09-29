"""Rungs 7 and 8: request-shape validation and pagination."""
import re

from flask import request

from errors import fail

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
STATE_RE = re.compile(r"^[A-Z]{2}$")
QUARTER_RE = re.compile(r"^[0-9]{4}Q[1-4]$")


def bad(msg):
    fail("ERR_INVALID_REQUEST", msg)


def body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        bad("Request body must be a JSON object.")
    return data


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def present(b, name):
    return name in b and b[name] is not None


def req_str(b, name, pattern=None, choices=None, allow_empty=False):
    if not present(b, name):
        bad("Field '%s' is required." % name)
    v = b[name]
    if not isinstance(v, str):
        bad("Field '%s' must be a string." % name)
    if not allow_empty and not v.strip():
        bad("Field '%s' must not be empty." % name)
    if pattern is not None and not pattern.match(v):
        bad("Field '%s' is malformed." % name)
    if choices is not None and v not in choices:
        bad("Field '%s' must be one of %s." % (name, ", ".join(choices)))
    return v


def opt_str(b, name, default=None, pattern=None, choices=None):
    if not present(b, name):
        return default
    return req_str(b, name, pattern=pattern, choices=choices)


def req_enum(b, name, choices):
    return req_str(b, name, choices=choices)


def opt_enum(b, name, choices, default=None):
    if not present(b, name):
        return default
    return req_str(b, name, choices=choices)


def req_int(b, name, minimum=None, maximum=None):
    if not present(b, name):
        bad("Field '%s' is required." % name)
    v = b[name]
    if not is_int(v):
        bad("Field '%s' must be an integer." % name)
    if minimum is not None and v < minimum:
        bad("Field '%s' must be at least %s." % (name, minimum))
    if maximum is not None and v > maximum:
        bad("Field '%s' must be at most %s." % (name, maximum))
    return v


def opt_int(b, name, default=None, minimum=None, maximum=None):
    if not present(b, name):
        return default
    return req_int(b, name, minimum=minimum, maximum=maximum)


def req_num(b, name, minimum=None, maximum=None):
    if not present(b, name):
        bad("Field '%s' is required." % name)
    v = b[name]
    if not is_num(v):
        bad("Field '%s' must be a number." % name)
    if minimum is not None and v < minimum:
        bad("Field '%s' must be at least %s." % (name, minimum))
    if maximum is not None and v > maximum:
        bad("Field '%s' must be at most %s." % (name, maximum))
    return v


def opt_num(b, name, default=None, minimum=None, maximum=None):
    if not present(b, name):
        return default
    return req_num(b, name, minimum=minimum, maximum=maximum)


def opt_bool(b, name, default=None):
    if not present(b, name):
        return default
    v = b[name]
    if not isinstance(v, bool):
        bad("Field '%s' must be a boolean." % name)
    return v


def req_str_list(b, name, choices=None, allow_empty=True):
    if not present(b, name):
        bad("Field '%s' is required." % name)
    v = b[name]
    if not isinstance(v, list):
        bad("Field '%s' must be an array." % name)
    if not allow_empty and not v:
        bad("Field '%s' must contain at least one element." % name)
    for item in v:
        if not isinstance(item, str):
            bad("Every element of '%s' must be a string." % name)
        if choices is not None and item not in choices:
            bad("Every element of '%s' must be one of %s." % (name, ", ".join(choices)))
    return v


def req_int_list(b, name, minimum=None, allow_empty=False):
    if not present(b, name):
        bad("Field '%s' is required." % name)
    v = b[name]
    if not isinstance(v, list):
        bad("Field '%s' must be an array." % name)
    if not allow_empty and not v:
        bad("Field '%s' must contain at least one element." % name)
    for item in v:
        if not is_int(item):
            bad("Every element of '%s' must be an integer." % name)
        if minimum is not None and item < minimum:
            bad("Every element of '%s' must be at least %s." % (name, minimum))
    return v


def req_num_list(b, name, minimum_exclusive=None, allow_empty=False):
    if not present(b, name):
        bad("Field '%s' is required." % name)
    v = b[name]
    if not isinstance(v, list):
        bad("Field '%s' must be an array." % name)
    if not allow_empty and not v:
        bad("Field '%s' must contain at least one element." % name)
    for item in v:
        if not is_num(item):
            bad("Every element of '%s' must be a number." % name)
        if minimum_exclusive is not None and item <= minimum_exclusive:
            bad("Every element of '%s' must be greater than %s." % (name, minimum_exclusive))
    return v


def absent(b, name, because):
    if name in b and b[name] is not None:
        bad("Field '%s' must be absent %s." % (name, because))


def _page_int(raw, name):
    if isinstance(raw, str):
        raw = raw.strip()
    try:
        value = int(raw)
    except (TypeError, ValueError):
        fail("ERR_INVALID_PAGINATION", "Query parameter '%s' must be an integer." % name)
    return value


def paginate():
    """Rung 8. Returns (limit, offset)."""
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args:
        limit = _page_int(args.get("limit"), "limit")
        if limit < 1 or limit > 100:
            fail("ERR_INVALID_PAGINATION", "Query parameter 'limit' must be between 1 and 100.")
    if "offset" in args:
        offset = _page_int(args.get("offset"), "offset")
        if offset < 0:
            fail("ERR_INVALID_PAGINATION", "Query parameter 'offset' must be at least 0.")
    return limit, offset


def slice_rows(rows, limit, offset):
    return rows[offset:offset + limit]
