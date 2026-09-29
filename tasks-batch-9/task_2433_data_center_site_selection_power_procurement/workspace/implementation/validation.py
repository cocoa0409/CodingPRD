"""Request-shape validation (PRD 2.8, admission ladder step 4).

Unknown body fields, and any attempt to write a computed or system-maintained
field, are silently ignored rather than rejected. Only declared fields are
checked: presence, type, enum membership and numeric range.
"""

import json
import re
from decimal import Decimal, InvalidOperation

from flask import request

import constants
from errors import ApiError
from timeutil import parse_dt

MISSING = object()
STATE_CODE_RE = re.compile(r"^[A-Z]{2}$")


class Field:
    def __init__(
        self,
        name,
        kind,
        required=True,
        default=MISSING,
        enum=None,
        ge=None,
        gt=None,
        le=None,
        lt=None,
        state_code=False,
    ):
        self.name = name
        self.kind = kind
        self.required = required
        self.default = default
        self.enum = enum
        self.ge = ge
        self.gt = gt
        self.le = le
        self.lt = lt
        self.state_code = state_code

    # -- coercion ------------------------------------------------------------
    def coerce(self, value):
        name = self.name
        if self.kind == "string":
            if not isinstance(value, str):
                raise ApiError("ERR_INVALID_REQUEST", "Field '%s' must be a string." % name)
            if self.state_code and not STATE_CODE_RE.match(value):
                raise ApiError(
                    "ERR_INVALID_REQUEST",
                    "Field '%s' must be exactly two uppercase letters." % name,
                )
            return value
        if self.kind == "enum":
            if not isinstance(value, str) or value not in self.enum:
                raise ApiError(
                    "ERR_INVALID_REQUEST",
                    "Field '%s' must be one of %s." % (name, ", ".join(self.enum)),
                )
            return value
        if self.kind == "datetime":
            if not isinstance(value, str):
                raise ApiError(
                    "ERR_INVALID_REQUEST", "Field '%s' must be an ISO 8601 string." % name
                )
            try:
                parse_dt(value)
            except Exception:
                raise ApiError(
                    "ERR_INVALID_REQUEST",
                    "Field '%s' must be a valid ISO 8601 instant." % name,
                )
            return value
        if self.kind == "integer":
            ivalue = _as_int(value, name)
            self._range(ivalue)
            return ivalue
        if self.kind == "number":
            dvalue = _as_decimal(value, name)
            self._range(dvalue)
            return dvalue
        if self.kind == "boolean":
            if not isinstance(value, bool):
                raise ApiError("ERR_INVALID_REQUEST", "Field '%s' must be a boolean." % name)
            return value
        raise ApiError("ERR_INVALID_REQUEST", "Unsupported field kind.")

    def _range(self, value):
        name = self.name
        if self.gt is not None and not value > self.gt:
            raise ApiError(
                "ERR_INVALID_REQUEST", "Field '%s' must be greater than %s." % (name, self.gt)
            )
        if self.ge is not None and not value >= self.ge:
            raise ApiError(
                "ERR_INVALID_REQUEST",
                "Field '%s' must be greater than or equal to %s." % (name, self.ge),
            )
        if self.lt is not None and not value < self.lt:
            raise ApiError(
                "ERR_INVALID_REQUEST", "Field '%s' must be less than %s." % (name, self.lt)
            )
        if self.le is not None and not value <= self.le:
            raise ApiError(
                "ERR_INVALID_REQUEST",
                "Field '%s' must be less than or equal to %s." % (name, self.le),
            )


def _as_decimal(value, name):
    if isinstance(value, bool):
        raise ApiError("ERR_INVALID_REQUEST", "Field '%s' must be a number." % name)
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        return Decimal(str(value))
    raise ApiError("ERR_INVALID_REQUEST", "Field '%s' must be a number." % name)


def _as_int(value, name):
    if isinstance(value, bool):
        raise ApiError("ERR_INVALID_REQUEST", "Field '%s' must be an integer." % name)
    if isinstance(value, int):
        return value
    if isinstance(value, (Decimal, float)):
        try:
            dvalue = value if isinstance(value, Decimal) else Decimal(str(value))
            if dvalue == dvalue.to_integral_value():
                return int(dvalue)
        except (InvalidOperation, ValueError):
            pass
    raise ApiError("ERR_INVALID_REQUEST", "Field '%s' must be an integer." % name)


def body():
    """Parsed JSON body; numbers are read as Decimal so money keeps its scale."""
    raw = request.get_data(as_text=True)
    if raw is None or raw.strip() == "":
        return {}
    try:
        parsed = json.loads(raw, parse_float=Decimal)
    except Exception:
        raise ApiError("ERR_INVALID_REQUEST", "The request body is not valid JSON.")
    if not isinstance(parsed, dict):
        raise ApiError("ERR_INVALID_REQUEST", "The request body must be a JSON object.")
    return parsed


def validate(fields, payload=None):
    payload = body() if payload is None else payload
    out = {}
    for field in fields:
        if field.name not in payload or payload[field.name] is None:
            if field.required:
                raise ApiError(
                    "ERR_INVALID_REQUEST", "Field '%s' is required." % field.name
                )
            out[field.name] = None if field.default is MISSING else field.default
            continue
        out[field.name] = field.coerce(payload[field.name])
    return out


def pagination():
    """PRD 2.3: limit defaults to 10 (1..100), offset defaults to 0 (>= 0)."""
    limit = constants.DEFAULT_LIMIT
    offset = constants.DEFAULT_OFFSET
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is not None and raw_limit != "":
        limit = _query_int("limit", raw_limit)
        if limit < constants.MIN_LIMIT or limit > constants.MAX_LIMIT:
            raise ApiError("ERR_INVALID_REQUEST", "limit must be between 1 and 100.")
    if raw_offset is not None and raw_offset != "":
        offset = _query_int("offset", raw_offset)
        if offset < 0:
            raise ApiError("ERR_INVALID_REQUEST", "offset must be zero or greater.")
    return limit, offset


def _query_int(name, raw):
    try:
        return int(raw)
    except (TypeError, ValueError):
        raise ApiError("ERR_INVALID_REQUEST", "%s must be an integer." % name)
