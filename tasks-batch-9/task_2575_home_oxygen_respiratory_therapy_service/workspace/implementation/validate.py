"""Request body validation.

Two passes so the global ladder is honoured: pass one covers required-field
presence, declared types, lengths and numeric ranges (ERR_INVALID_REQUEST,
position 17); pass two covers enumeration membership (ERR_INVALID_ENUM_VALUE,
position 18).
"""
import re

from flask import request

from core import (
    ApiError,
    parse_date_value,
    parse_datetime,
    parse_month_value,
    dec,
)

MISSING = object()


class Field(object):
    def __init__(
        self,
        name,
        kind,
        required=False,
        nullable=False,
        default=MISSING,
        minimum=None,
        maximum=None,
        min_len=None,
        max_len=None,
        enum=None,
        pattern=None,
        item_kind=None,
    ):
        self.name = name
        self.kind = kind
        self.required = required
        self.nullable = nullable
        self.default = default
        self.minimum = minimum
        self.maximum = maximum
        self.min_len = min_len
        self.max_len = max_len
        self.enum = enum
        self.pattern = pattern
        self.item_kind = item_kind


def body_object():
    """The parsed JSON body, or an empty object when absent/not an object."""
    try:
        data = request.get_json(silent=True, force=True)
    except Exception:
        data = None
    if isinstance(data, dict):
        return data
    return {}


def _bad(field, detail):
    raise ApiError("ERR_INVALID_REQUEST", "%s %s" % (field, detail))


def _check_scalar(field, value):
    kind = field.kind
    if kind == "string":
        if not isinstance(value, str):
            _bad(field.name, "must be a string")
        if field.min_len is not None and len(value) < field.min_len:
            _bad(field.name, "is too short")
        if field.max_len is not None and len(value) > field.max_len:
            _bad(field.name, "is too long")
        if field.pattern is not None and not re.match(field.pattern, value):
            _bad(field.name, "has an invalid format")
        return value
    if kind == "integer":
        if isinstance(value, bool) or not isinstance(value, int):
            _bad(field.name, "must be an integer")
        if field.minimum is not None and value < field.minimum:
            _bad(field.name, "is below the allowed minimum")
        if field.maximum is not None and value > field.maximum:
            _bad(field.name, "is above the allowed maximum")
        return value
    if kind == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            _bad(field.name, "must be a number")
        val = dec(value)
        if field.minimum is not None and val < dec(field.minimum):
            _bad(field.name, "is below the allowed minimum")
        if field.maximum is not None and val > dec(field.maximum):
            _bad(field.name, "is above the allowed maximum")
        return value
    if kind == "boolean":
        if not isinstance(value, bool):
            _bad(field.name, "must be a boolean")
        return value
    if kind == "date":
        parsed = parse_date_value(value)
        if parsed is None:
            _bad(field.name, "must be a YYYY-MM-DD date")
        return value
    if kind == "datetime":
        parsed = parse_datetime(value)
        if parsed is None:
            _bad(field.name, "must be an ISO 8601 timestamp")
        return value
    if kind == "month":
        parsed = parse_month_value(value)
        if parsed is None:
            _bad(field.name, "must be a YYYY-MM month")
        return value
    if kind == "array":
        if not isinstance(value, list):
            _bad(field.name, "must be an array")
        for item in value:
            if field.item_kind == "string" and not isinstance(item, str):
                _bad(field.name, "must contain only strings")
        return value
    if kind == "enum":
        return value
    return value


def validate(fields, body=None):
    """Validate a request body against the declared field list."""
    if body is None:
        body = body_object()
    result = {}
    # pass one: presence, types, lengths, ranges
    for field in fields:
        if field.name not in body:
            if field.required:
                raise ApiError(
                    "ERR_INVALID_REQUEST", "%s is required" % field.name
                )
            if field.default is not MISSING:
                result[field.name] = field.default
            continue
        value = body[field.name]
        if value is None:
            if field.nullable:
                result[field.name] = None
                continue
            _bad(field.name, "must not be null")
        result[field.name] = _check_scalar(field, value)
    # pass two: enumeration membership
    for field in fields:
        if field.enum is None:
            continue
        if field.name not in result:
            continue
        value = result[field.name]
        if value is None:
            continue
        if value not in field.enum:
            raise ApiError(
                "ERR_INVALID_ENUM_VALUE",
                "%s is not a permitted value for %s" % (value, field.name),
            )
    return result


def has_field(name, body=None):
    if body is None:
        body = body_object()
    return name in body
