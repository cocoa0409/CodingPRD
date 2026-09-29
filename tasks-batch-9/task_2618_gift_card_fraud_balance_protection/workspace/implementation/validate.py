"""Tier-4 well-formedness helpers (PRD 2.8 priority 25) and pagination
(PRD 2.3). Derived/computed fields arriving in a body are silently ignored."""
import re

from flask import request

import clock
from errors import fail

MASKED_PAN_RE = re.compile(r"^\*{4}-\*{4}-\*{4}-[0-9]{4}$")
REGION_CODE_RE = re.compile(r"^[A-Z]{2}$")

_MISSING = object()


def body():
    if not request.data:
        return {}
    parsed = request.get_json(silent=True)
    if parsed is None:
        fail("ERR_INVALID_REQUEST", "Request body is not valid JSON.")
    if not isinstance(parsed, dict):
        fail("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return parsed


def _raw(b, name):
    return b.get(name, _MISSING)


def _bad(name, why="is invalid"):
    fail("ERR_INVALID_REQUEST", "Field '%s' %s." % (name, why))


def string(b, name, required=True, min_len=1, max_len=None, pattern=None):
    value = _raw(b, name)
    if value is _MISSING or value is None:
        if required:
            _bad(name, "is required")
        return None
    if not isinstance(value, str):
        _bad(name, "must be a string")
    if min_len is not None and len(value) < min_len:
        _bad(name, "is too short")
    if max_len is not None and len(value) > max_len:
        _bad(name, "is too long")
    if pattern is not None and not pattern.match(value):
        _bad(name, "does not match the required pattern")
    return value


def integer(b, name, required=True, minimum=None, maximum=None):
    value = _raw(b, name)
    if value is _MISSING or value is None:
        if required:
            _bad(name, "is required")
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        _bad(name, "must be an integer")
    if minimum is not None and value < minimum:
        _bad(name, "is below the permitted minimum")
    if maximum is not None and value > maximum:
        _bad(name, "is above the permitted maximum")
    return value


def boolean(b, name, required=True):
    value = _raw(b, name)
    if value is _MISSING or value is None:
        if required:
            _bad(name, "is required")
        return None
    if not isinstance(value, bool):
        _bad(name, "must be a boolean")
    return value


def enum(b, name, allowed, required=True):
    value = _raw(b, name)
    if value is _MISSING or value is None:
        if required:
            _bad(name, "is required")
        return None
    if not isinstance(value, str) or value not in allowed:
        _bad(name, "is not one of %s" % (", ".join(allowed),))
    return value


def datetime_field(b, name, required=True):
    value = _raw(b, name)
    if value is _MISSING or value is None:
        if required:
            _bad(name, "is required")
        return None
    parsed = clock.parse(value)
    if parsed is None:
        _bad(name, "is not a valid ISO-8601 UTC instant")
    return parsed


def string_list(b, name, allowed=None, required=True):
    value = _raw(b, name)
    if value is _MISSING or value is None:
        if required:
            _bad(name, "is required")
        return None
    if not isinstance(value, list):
        _bad(name, "must be an array")
    for item in value:
        if not isinstance(item, str):
            _bad(name, "must contain only strings")
        if allowed is not None and item not in allowed:
            _bad(name, "contains an unrecognised value")
    return value


def absent(b, name):
    """A field that this variant forbids."""
    if b.get(name, _MISSING) not in (_MISSING, None):
        _bad(name, "must be omitted for this channel")


def pagination():
    limit = 10
    offset = 0
    raw_limit = request.args.get("limit")
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            _bad("limit", "must be an integer")
        if limit < 1 or limit > 100:
            _bad("limit", "must be between 1 and 100")
    raw_offset = request.args.get("offset")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            _bad("offset", "must be an integer")
        if offset < 0:
            _bad("offset", "must be 0 or greater")
    return limit, offset


def query_enum(name, allowed):
    value = request.args.get(name)
    if value is None:
        return None
    if value not in allowed:
        _bad(name, "is not a recognised filter value")
    return value


def query_str(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    return value


def paginate(rows, limit, offset):
    return rows[offset:offset + limit], len(rows)
