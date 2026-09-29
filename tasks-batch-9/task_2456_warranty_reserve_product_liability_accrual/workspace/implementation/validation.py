"""Request-shape conformance (PRD §2.9 rung 5) and pagination parsing (§2.3)."""

import re
from datetime import date, datetime, timezone

from flask import request

from errors import fail
from response import (
    PAGINATION_DEFAULT_LIMIT,
    PAGINATION_DEFAULT_OFFSET,
    PAGINATION_MAX_LIMIT,
    PAGINATION_MIN_LIMIT,
    PAGINATION_MIN_OFFSET,
)

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
PERIOD_CODE_RE = re.compile(r"^\d{4}-Q[1-4]$")

MISSING = object()


class Field:
    def __init__(
        self,
        name,
        kind,
        required=True,
        minimum=None,
        maximum=None,
        enum=None,
        nullable=False,
        default=None,
    ):
        self.name = name
        self.kind = kind
        self.required = required
        self.minimum = minimum
        self.maximum = maximum
        self.enum = enum
        self.nullable = nullable
        self.default = default


def parse_date(value):
    """Strict ``YYYY-MM-DD`` parse; returns a ``datetime.date`` or None."""
    if not isinstance(value, str) or not DATE_RE.match(value):
        return None
    try:
        return date(int(value[0:4]), int(value[5:7]), int(value[8:10]))
    except ValueError:
        return None


def parse_iso_instant(value):
    """Parse an ISO 8601 instant, tolerating ``Z`` and fractional seconds."""
    if not isinstance(value, str) or not value:
        return None
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _check_value(field, value):
    kind = field.kind
    if value is None:
        if field.nullable:
            return None
        fail("ERR_INVALID_REQUEST", "Field '%s' may not be null." % field.name)
    if kind == "int":
        if isinstance(value, bool) or not isinstance(value, int):
            fail("ERR_INVALID_REQUEST", "Field '%s' must be an integer." % field.name)
        if field.minimum is not None and value < field.minimum:
            fail("ERR_INVALID_REQUEST", "Field '%s' is below its minimum." % field.name)
        if field.maximum is not None and value > field.maximum:
            fail("ERR_INVALID_REQUEST", "Field '%s' is above its maximum." % field.name)
        return value
    if kind == "bool":
        if not isinstance(value, bool):
            fail("ERR_INVALID_REQUEST", "Field '%s' must be a boolean." % field.name)
        return value
    if kind == "str":
        if not isinstance(value, str):
            fail("ERR_INVALID_REQUEST", "Field '%s' must be a string." % field.name)
        if value == "":
            fail("ERR_INVALID_REQUEST", "Field '%s' must not be empty." % field.name)
        return value
    if kind == "id":
        if not isinstance(value, str) or value == "":
            fail("ERR_INVALID_REQUEST", "Field '%s' must be an identifier string." % field.name)
        return value
    if kind == "enum":
        if not isinstance(value, str) or value not in field.enum:
            fail("ERR_INVALID_REQUEST", "Field '%s' is not a declared enum member." % field.name)
        return value
    if kind == "date":
        if parse_date(value) is None:
            fail("ERR_INVALID_REQUEST", "Field '%s' must be a YYYY-MM-DD date." % field.name)
        return value
    if kind == "period_code":
        if not isinstance(value, str) or not PERIOD_CODE_RE.match(value):
            fail("ERR_INVALID_REQUEST", "Field '%s' must match YYYY-QN." % field.name)
        return value
    if kind == "iso":
        if parse_iso_instant(value) is None:
            fail("ERR_INVALID_REQUEST", "Field '%s' must be an ISO 8601 instant." % field.name)
        return value
    raise AssertionError("unknown field kind " + kind)


def raw_body():
    """The JSON body as a dict.  Absent, empty or malformed bodies read as {}."""
    if not request.data:
        return {}
    body = request.get_json(silent=True, force=True)
    if body is None:
        fail("ERR_INVALID_REQUEST", "The request body is not valid JSON.")
    if not isinstance(body, dict):
        fail("ERR_INVALID_REQUEST", "The request body must be a JSON object.")
    return body


def validate_body(fields):
    """Validate the request body against ``fields``.

    Returns ``(values, present)`` where ``values`` maps every declared field to
    its value (defaults filled in) and ``present`` is the set of field names the
    client actually supplied.
    """
    body = raw_body()
    declared = {f.name: f for f in fields}
    for key in body:
        if key not in declared:
            fail("ERR_INVALID_REQUEST", "Unknown field '%s'." % key)
    values = {}
    present = set()
    for field in fields:
        if field.name not in body:
            if field.required:
                fail("ERR_INVALID_REQUEST", "Field '%s' is required." % field.name)
            values[field.name] = field.default
            continue
        present.add(field.name)
        values[field.name] = _check_value(field, body[field.name])
    return values, present


def no_body():
    """Endpoints whose declared input is empty accept no field at all."""
    body = raw_body()
    if body:
        fail("ERR_INVALID_REQUEST", "This endpoint accepts no request body fields.")
    return {}


def pagination():
    """limit / offset with the declared defaults, minima and maxima."""
    limit = PAGINATION_DEFAULT_LIMIT
    offset = PAGINATION_DEFAULT_OFFSET
    raw_limit = request.args.get("limit")
    if raw_limit is not None:
        if not re.match(r"^-?\d+$", raw_limit.strip()):
            fail("ERR_INVALID_REQUEST", "limit must be an integer.")
        limit = int(raw_limit)
        if limit < PAGINATION_MIN_LIMIT or limit > PAGINATION_MAX_LIMIT:
            fail("ERR_INVALID_REQUEST", "limit is out of bounds.")
    raw_offset = request.args.get("offset")
    if raw_offset is not None:
        if not re.match(r"^-?\d+$", raw_offset.strip()):
            fail("ERR_INVALID_REQUEST", "offset must be an integer.")
        offset = int(raw_offset)
        if offset < PAGINATION_MIN_OFFSET:
            fail("ERR_INVALID_REQUEST", "offset is out of bounds.")
    return limit, offset


def paginate(rows, limit, offset):
    return rows[offset : offset + limit]


def query_filter(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    return value
