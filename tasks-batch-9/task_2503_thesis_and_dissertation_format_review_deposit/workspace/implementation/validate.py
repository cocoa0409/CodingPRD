"""Stage 3 of the admission ladder: payload shape (PRD section 2.5)."""

import re

from flask import request

from errors import fail
from timeutil import parse_iso

_INT_RE = re.compile(r"^-?\d+$")


def _bad(message):
    fail("ERR_INVALID_REQUEST", message)


def get_body():
    if not request.data:
        return {}
    body = request.get_json(silent=True)
    if body is None:
        _bad("Request body must be a JSON object")
    if not isinstance(body, dict):
        _bad("Request body must be a JSON object")
    return body


def _present(body, name):
    return name in body and body[name] is not None


def req_str(body, name, allow_empty=True):
    if not _present(body, name):
        _bad("Field '%s' is required" % name)
    value = body[name]
    if not isinstance(value, str):
        _bad("Field '%s' must be a string" % name)
    if not allow_empty and value == "":
        _bad("Field '%s' must be a non-empty string" % name)
    return value


def opt_str(body, name, default=None):
    if not _present(body, name):
        return default
    value = body[name]
    if not isinstance(value, str):
        _bad("Field '%s' must be a string" % name)
    return value


def req_int(body, name, minimum=None, maximum=None):
    if not _present(body, name):
        _bad("Field '%s' is required" % name)
    value = body[name]
    if isinstance(value, bool) or not isinstance(value, int):
        _bad("Field '%s' must be an integer" % name)
    if minimum is not None and value < minimum:
        _bad("Field '%s' must be at least %s" % (name, minimum))
    if maximum is not None and value > maximum:
        _bad("Field '%s' must be at most %s" % (name, maximum))
    return value


def opt_int(body, name, default=None, minimum=None, maximum=None):
    if not _present(body, name):
        return default
    return req_int(body, name, minimum=minimum, maximum=maximum)


def req_num(body, name, minimum=None, maximum=None):
    if not _present(body, name):
        _bad("Field '%s' is required" % name)
    value = body[name]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _bad("Field '%s' must be a number" % name)
    if minimum is not None and value < minimum:
        _bad("Field '%s' must be at least %s" % (name, minimum))
    if maximum is not None and value > maximum:
        _bad("Field '%s' must be at most %s" % (name, maximum))
    return value


def opt_num(body, name, default=None, minimum=None, maximum=None):
    if not _present(body, name):
        return default
    return req_num(body, name, minimum=minimum, maximum=maximum)


def req_bool(body, name):
    if not _present(body, name):
        _bad("Field '%s' is required" % name)
    if not isinstance(body[name], bool):
        _bad("Field '%s' must be a boolean" % name)
    return body[name]


def opt_bool(body, name, default=None):
    if not _present(body, name):
        return default
    return req_bool(body, name)


def req_enum(body, name, allowed):
    value = req_str(body, name)
    if value not in allowed:
        _bad("Field '%s' must be one of %s" % (name, sorted(allowed)))
    return value


def opt_enum(body, name, allowed, default=None):
    if not _present(body, name):
        return default
    return req_enum(body, name, allowed)


def req_datetime(body, name):
    value = req_str(body, name)
    parsed = parse_iso(value)
    if parsed is None:
        _bad("Field '%s' must be an ISO 8601 instant" % name)
    return parsed


def req_str_list(body, name):
    if not _present(body, name):
        _bad("Field '%s' is required" % name)
    value = body[name]
    if not isinstance(value, list):
        _bad("Field '%s' must be an array" % name)
    for item in value:
        if not isinstance(item, str):
            _bad("Field '%s' must be an array of strings" % name)
    return list(value)


def pagination():
    """limit default 10 (1..100), offset default 0 (min 0)."""
    limit = 10
    offset = 0
    raw_limit = request.args.get("limit")
    if raw_limit is not None:
        text = raw_limit.strip()
        if not _INT_RE.match(text):
            _bad("Query parameter 'limit' must be an integer")
        limit = int(text)
        if limit < 1 or limit > 100:
            _bad("Query parameter 'limit' must be between 1 and 100")
    raw_offset = request.args.get("offset")
    if raw_offset is not None:
        text = raw_offset.strip()
        if not _INT_RE.match(text):
            _bad("Query parameter 'offset' must be an integer")
        offset = int(text)
        if offset < 0:
            _bad("Query parameter 'offset' must be at least 0")
    return limit, offset


def query_enum(name, allowed):
    value = request.args.get(name)
    if value is None:
        return None
    if value not in allowed:
        _bad("Query parameter '%s' must be one of %s" % (name, sorted(allowed)))
    return value


def query_str(name):
    return request.args.get(name)


def paginate(rows, limit, offset):
    return rows[offset : offset + limit], len(rows)
