"""Request-shape validation (ladder step 5) and pagination parsing (PRD 2.3)."""

from flask import request

import clock
from errors import ApiError
from money import dec, q2

MISSING = object()


class Field:
    """One declared body field: its name, kind, requiredness and range constraint."""

    def __init__(self, name, kind, required=True, enum=None, check=None, default=MISSING):
        self.name = name
        self.kind = kind
        self.required = required
        self.enum = enum
        self.check = check
        self.default = default


def bad_request(detail=None):
    return ApiError("ERR_INVALID_REQUEST", detail)


def parse_body():
    """The body must parse as a JSON object; an absent body is an empty object."""
    raw = request.get_data()
    if raw is None or len(raw.strip()) == 0:
        return {}
    try:
        body = request.get_json(force=True, silent=False)
    except Exception:
        raise bad_request("The request body is not valid JSON.")
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise bad_request("The request body must be a JSON object.")
    return body


def _coerce(field, value):
    kind = field.kind
    if kind == "string":
        if not isinstance(value, str):
            raise bad_request("%s must be a string." % field.name)
        return value
    if kind == "boolean":
        if not isinstance(value, bool):
            raise bad_request("%s must be a boolean." % field.name)
        return value
    if kind == "integer":
        if isinstance(value, bool) or not isinstance(value, int):
            raise bad_request("%s must be an integer." % field.name)
        return value
    if kind in ("number", "money"):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise bad_request("%s must be a number." % field.name)
        parsed = dec(value)
        return q2(parsed) if kind == "money" else parsed
    if kind == "datetime":
        try:
            return clock.parse_dt(value)
        except (ValueError, TypeError):
            raise bad_request("%s must be an ISO 8601 timestamp." % field.name)
    if kind == "enum":
        if not isinstance(value, str) or value not in field.enum:
            raise bad_request("%s must be one of %s." % (field.name, ", ".join(field.enum)))
        return value
    raise bad_request("%s could not be validated." % field.name)


def validate(body, fields):
    """Return (values, provided_names). Nulls on optional fields are honoured."""
    values = {}
    provided = set()
    for field in fields:
        if field.name not in body:
            if field.required:
                raise bad_request("%s is required." % field.name)
            if field.default is not MISSING:
                values[field.name] = field.default
            continue
        raw = body[field.name]
        if raw is None:
            if field.required:
                raise bad_request("%s is required." % field.name)
            provided.add(field.name)
            values[field.name] = None
            continue
        value = _coerce(field, raw)
        if field.check is not None and not field.check(value):
            raise bad_request("%s is outside its permitted range." % field.name)
        values[field.name] = value
        provided.add(field.name)
    return values, provided


def parse_pagination():
    """limit defaults to 10 (1..100); offset defaults to 0 (>= 0)."""
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    limit = 10
    offset = 0
    if limit_raw is not None:
        try:
            limit = int(str(limit_raw).strip())
        except (TypeError, ValueError):
            raise bad_request("limit must be an integer between 1 and 100.")
        if limit < 1 or limit > 100:
            raise bad_request("limit must be between 1 and 100.")
    if offset_raw is not None:
        try:
            offset = int(str(offset_raw).strip())
        except (TypeError, ValueError):
            raise bad_request("offset must be an integer of at least 0.")
        if offset < 0:
            raise bad_request("offset must be at least 0.")
    return limit, offset


def paginate(records, limit, offset):
    return records[offset : offset + limit]
