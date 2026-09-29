"""Request-shape validation: ladder priority 4, always ERR_INVALID_REQUEST.

No unknown body or query fields, all required fields present, every enumeration
value within its declared range, integers non-negative where declared
non-negative, decimals within their declared scale, limit within 1..100 and
offset zero or greater.
"""
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from flask import request

from errors import fail
from response import (
    PAGINATION_DEFAULT_LIMIT,
    PAGINATION_DEFAULT_OFFSET,
    PAGINATION_MAX_LIMIT,
    PAGINATION_MIN_LIMIT,
)

MISSING = object()


def parse_dt(value):
    """Accept an ISO 8601 instant (Z, numeric offset or naive) or a bare date."""
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    if not isinstance(value, str) or value.strip() == "":
        return None
    raw = value.strip()
    candidate = raw
    if candidate.endswith("Z") or candidate.endswith("z"):
        candidate = candidate[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M"):
            try:
                parsed = datetime.strptime(raw, fmt)
                break
            except ValueError:
                parsed = None
        if parsed is None:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


class Field(object):
    """Declared shape of one body or query field."""

    def __init__(
        self,
        name,
        kind="string",
        required=True,
        default=MISSING,
        enum=None,
        scale=None,
        nullable=False,
        min_value=None,
        gt=None,
        max_value=None,
    ):
        self.name = name
        self.kind = kind
        self.required = required
        self.default = default
        self.enum = enum
        self.scale = scale
        self.nullable = nullable
        self.min_value = min_value
        self.gt = gt
        self.max_value = max_value

    # -- coercion ---------------------------------------------------------
    def coerce(self, value, from_query=False):
        name = self.name
        if value is None:
            if self.nullable or (not self.required and self.default is None):
                return None
            fail("ERR_INVALID_REQUEST", "Field '%s' may not be null." % name)

        if self.kind == "string" or self.kind == "enum":
            if not isinstance(value, str):
                fail("ERR_INVALID_REQUEST", "Field '%s' must be a string." % name)
            if value.strip() == "":
                fail("ERR_INVALID_REQUEST", "Field '%s' may not be empty." % name)
            if self.enum is not None and value not in self.enum:
                fail(
                    "ERR_INVALID_REQUEST",
                    "Field '%s' must be one of %s." % (name, ", ".join(self.enum)),
                )
            return value

        if self.kind == "bool":
            if from_query:
                low = str(value).lower()
                if low in ("true", "1"):
                    return True
                if low in ("false", "0"):
                    return False
                fail("ERR_INVALID_REQUEST", "Field '%s' must be a boolean." % name)
            if not isinstance(value, bool):
                fail("ERR_INVALID_REQUEST", "Field '%s' must be a boolean." % name)
            return value

        if self.kind == "int":
            parsed = self._as_int(value, from_query)
            self._range_check(parsed)
            return parsed

        if self.kind == "number":
            parsed = self._as_decimal(value, from_query)
            if self.scale is not None and -parsed.as_tuple().exponent > self.scale:
                fail(
                    "ERR_INVALID_REQUEST",
                    "Field '%s' may not carry more than %d decimal places."
                    % (name, self.scale),
                )
            self._range_check(parsed)
            return parsed

        if self.kind == "datetime":
            parsed = parse_dt(value)
            if parsed is None:
                fail(
                    "ERR_INVALID_REQUEST",
                    "Field '%s' must be an ISO 8601 timestamp." % name,
                )
            return parsed

        return value

    def _as_int(self, value, from_query):
        if isinstance(value, bool):
            fail("ERR_INVALID_REQUEST", "Field '%s' must be an integer." % self.name)
        if isinstance(value, int):
            return value
        if from_query and isinstance(value, str):
            try:
                return int(value.strip())
            except ValueError:
                fail(
                    "ERR_INVALID_REQUEST",
                    "Field '%s' must be an integer." % self.name,
                )
        fail("ERR_INVALID_REQUEST", "Field '%s' must be an integer." % self.name)

    def _as_decimal(self, value, from_query):
        if isinstance(value, bool):
            fail("ERR_INVALID_REQUEST", "Field '%s' must be a number." % self.name)
        if isinstance(value, int):
            return Decimal(value)
        if isinstance(value, float):
            return Decimal(repr(value))
        if from_query and isinstance(value, str):
            try:
                return Decimal(value.strip())
            except InvalidOperation:
                fail("ERR_INVALID_REQUEST", "Field '%s' must be a number." % self.name)
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a number." % self.name)

    def _range_check(self, parsed):
        if self.min_value is not None and parsed < self.min_value:
            fail(
                "ERR_INVALID_REQUEST",
                "Field '%s' must be at least %s." % (self.name, self.min_value),
            )
        if self.gt is not None and parsed <= self.gt:
            fail(
                "ERR_INVALID_REQUEST",
                "Field '%s' must be strictly greater than %s." % (self.name, self.gt),
            )
        if self.max_value is not None and parsed > self.max_value:
            fail(
                "ERR_INVALID_REQUEST",
                "Field '%s' may not exceed %s." % (self.name, self.max_value),
            )


def raw_body():
    """The JSON body, or {} when the request carries none."""
    data = request.get_data(cache=True, as_text=True)
    if data is None or data.strip() == "":
        return {}
    body = request.get_json(silent=True)
    if body is None:
        fail("ERR_INVALID_REQUEST", "The request body is not valid JSON.")
    if not isinstance(body, dict):
        fail("ERR_INVALID_REQUEST", "The request body must be a JSON object.")
    return body


def read_body(fields):
    """Validate the JSON body against an ordered list of Field declarations."""
    body = raw_body()
    known = set(f.name for f in fields)
    for key in body.keys():
        if key not in known:
            fail("ERR_INVALID_REQUEST", "Unknown body field '%s'." % key)
    out = {}
    for spec in fields:
        if spec.name in body:
            out[spec.name] = spec.coerce(body[spec.name])
        elif spec.required:
            fail("ERR_INVALID_REQUEST", "Field '%s' is required." % spec.name)
        elif spec.default is not MISSING:
            out[spec.name] = spec.default
    return out


def read_query(fields):
    """Validate query parameters; limit/offset are always accepted."""
    known = set(f.name for f in fields) | set(("limit", "offset"))
    for key in request.args.keys():
        if key not in known:
            fail("ERR_INVALID_REQUEST", "Unknown query parameter '%s'." % key)
    out = {}
    for spec in fields:
        if spec.name in request.args:
            out[spec.name] = spec.coerce(request.args.get(spec.name), from_query=True)
    return out


def read_page():
    """limit within 1..100 and offset zero or greater."""
    limit = PAGINATION_DEFAULT_LIMIT
    offset = PAGINATION_DEFAULT_OFFSET
    if "limit" in request.args:
        limit = Field(
            "limit",
            "int",
            min_value=PAGINATION_MIN_LIMIT,
            max_value=PAGINATION_MAX_LIMIT,
        ).coerce(request.args.get("limit"), from_query=True)
    if "offset" in request.args:
        offset = Field("offset", "int", min_value=0).coerce(
            request.args.get("offset"), from_query=True
        )
    return limit, offset


def no_body():
    """Endpoints declaring no input accept an empty body only."""
    body = raw_body()
    for key in body.keys():
        fail("ERR_INVALID_REQUEST", "Unknown body field '%s'." % key)
    for key in request.args.keys():
        fail("ERR_INVALID_REQUEST", "Unknown query parameter '%s'." % key)
    return {}
