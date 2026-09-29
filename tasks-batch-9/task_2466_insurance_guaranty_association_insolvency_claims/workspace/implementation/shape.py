"""Request-shape validation (PRD 2.8 priority 14) and pagination parsing (PRD 2.3).

Every failure in this module is ERR_INVALID_REQUEST (HTTP 400): missing required
field, wrong type, value outside the declared range, unknown enum member and
unknown field.
"""

import re

from flask import request

from errors import fail
from store import parse_date, parse_datetime

STATE_CODE_RE = re.compile(r"^[A-Z]{2}$")


class F(object):
    """One declared request-body field."""

    def __init__(
        self,
        name,
        kind,
        required=True,
        default=None,
        enum=None,
        minimum=None,
        maximum=None,
        exclusive_minimum=None,
        state_code=False,
        allow_empty=False,
        min_items=None,
    ):
        self.name = name
        self.kind = kind
        self.required = required
        self.default = default
        self.enum = enum
        self.minimum = minimum
        self.maximum = maximum
        self.exclusive_minimum = exclusive_minimum
        self.state_code = state_code
        self.allow_empty = allow_empty
        self.min_items = min_items


def get_body():
    """Parse the JSON body; an absent body is an empty object."""
    raw = request.get_data(cache=True, as_text=True)
    if raw is None or raw.strip() == "":
        return {}
    parsed = request.get_json(silent=True)
    if parsed is None:
        fail("ERR_INVALID_REQUEST", "Request body is not valid JSON.")
    if not isinstance(parsed, dict):
        fail("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return parsed


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number(value):
    return (isinstance(value, int) or isinstance(value, float)) and not isinstance(value, bool)


def validate(body, fields):
    """Validate `body` against the declared `fields`; returns the coerced values."""
    declared = set(f.name for f in fields)
    for key in body.keys():
        if key not in declared:
            fail("ERR_INVALID_REQUEST", "Unknown field '%s'." % key)

    values = {}
    for spec in fields:
        present = spec.name in body and body[spec.name] is not None
        if not present:
            if spec.required:
                fail("ERR_INVALID_REQUEST", "Field '%s' is required." % spec.name)
            values[spec.name] = spec.default
            continue
        values[spec.name] = _check(spec, body[spec.name])
    return values


def _check(spec, value):
    name = spec.name
    kind = spec.kind

    if kind == "str":
        if not isinstance(value, str):
            fail("ERR_INVALID_REQUEST", "Field '%s' must be a string." % name)
        if not spec.allow_empty and value.strip() == "":
            fail("ERR_INVALID_REQUEST", "Field '%s' must not be empty." % name)
        if spec.state_code and not STATE_CODE_RE.match(value):
            fail(
                "ERR_INVALID_REQUEST",
                "Field '%s' must be exactly two uppercase letters." % name,
            )
        if spec.enum is not None and value not in spec.enum:
            fail("ERR_INVALID_REQUEST", "Field '%s' must be one of %s." % (name, spec.enum))
        return value

    if kind == "enum":
        if not isinstance(value, str):
            fail("ERR_INVALID_REQUEST", "Field '%s' must be a string." % name)
        if value not in spec.enum:
            fail("ERR_INVALID_REQUEST", "Field '%s' must be one of %s." % (name, spec.enum))
        return value

    if kind == "int":
        if not _is_int(value):
            fail("ERR_INVALID_REQUEST", "Field '%s' must be an integer." % name)
        _range_check(spec, value)
        return value

    if kind == "number":
        if not _is_number(value):
            fail("ERR_INVALID_REQUEST", "Field '%s' must be a number." % name)
        _range_check(spec, value)
        return value

    if kind == "bool":
        if not isinstance(value, bool):
            fail("ERR_INVALID_REQUEST", "Field '%s' must be a boolean." % name)
        return value

    if kind == "date":
        if parse_date(value) is None:
            fail(
                "ERR_INVALID_REQUEST",
                "Field '%s' must be an ISO 8601 calendar date (YYYY-MM-DD)." % name,
            )
        return value

    if kind == "datetime":
        if parse_datetime(value) is None:
            fail("ERR_INVALID_REQUEST", "Field '%s' must be an ISO 8601 instant." % name)
        return value

    if kind == "array":
        if not isinstance(value, list):
            fail("ERR_INVALID_REQUEST", "Field '%s' must be an array." % name)
        if spec.min_items is not None and len(value) < spec.min_items:
            fail(
                "ERR_INVALID_REQUEST",
                "Field '%s' must contain at least %d element(s)." % (name, spec.min_items),
            )
        return value

    if kind == "object":
        if not isinstance(value, dict):
            fail("ERR_INVALID_REQUEST", "Field '%s' must be an object." % name)
        return value

    if kind == "any":
        return value

    fail("ERR_INVALID_REQUEST", "Field '%s' is not understood." % name)


def _range_check(spec, value):
    if spec.exclusive_minimum is not None and value <= spec.exclusive_minimum:
        fail(
            "ERR_INVALID_REQUEST",
            "Field '%s' must be greater than %s." % (spec.name, spec.exclusive_minimum),
        )
    if spec.minimum is not None and value < spec.minimum:
        fail(
            "ERR_INVALID_REQUEST",
            "Field '%s' must be at least %s." % (spec.name, spec.minimum),
        )
    if spec.maximum is not None and value > spec.maximum:
        fail(
            "ERR_INVALID_REQUEST",
            "Field '%s' must be at most %s." % (spec.name, spec.maximum),
        )


def no_body():
    """Endpoints that declare no input accept no field at all."""
    body = get_body()
    if body:
        fail("ERR_INVALID_REQUEST", "This endpoint accepts no request body fields.")
    return {}


def pagination():
    """limit default 10 (min 1, max 100); offset default 0 (min 0) -- PRD 2.3."""
    limit = 10
    offset = 0
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is not None:
        limit = _query_int("limit", raw_limit)
        if limit < 1 or limit > 100:
            fail("ERR_INVALID_REQUEST", "Query parameter 'limit' must be between 1 and 100.")
    if raw_offset is not None:
        offset = _query_int("offset", raw_offset)
        if offset < 0:
            fail("ERR_INVALID_REQUEST", "Query parameter 'offset' must be at least 0.")
    return limit, offset


def _query_int(name, raw):
    try:
        return int(raw)
    except (TypeError, ValueError):
        fail("ERR_INVALID_REQUEST", "Query parameter '%s' must be an integer." % name)


def enum_filter(name, allowed):
    value = request.args.get(name)
    if value is None:
        return None
    if value not in allowed:
        fail("ERR_INVALID_REQUEST", "Query parameter '%s' must be one of %s." % (name, allowed))
    return value


def str_filter(name):
    return request.args.get(name)


def paginate(rows, limit, offset):
    return rows[offset : offset + limit], len(rows)
