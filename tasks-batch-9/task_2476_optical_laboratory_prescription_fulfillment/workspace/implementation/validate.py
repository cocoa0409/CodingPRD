"""Structural well-formedness (validation priority 10 -> ERR_VALIDATION)."""

import re
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation

from flask import request

from errors import ApiError

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def bad():
    raise ApiError("ERR_VALIDATION")


def json_body():
    body = request.get_json(force=True, silent=True)
    if body is None:
        if not request.get_data():
            return {}
        bad()
    if not isinstance(body, dict):
        bad()
    return body


def parse_date(value):
    if not isinstance(value, str) or not _DATE_RE.match(value):
        return None
    try:
        return date(int(value[0:4]), int(value[5:7]), int(value[8:10]))
    except ValueError:
        return None


def parse_datetime(value):
    if not isinstance(value, str) or not value:
        return None
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def to_decimal(value):
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


class F(object):
    """Declaration of one input field."""

    def __init__(self, name, kind, required=True, enum=None, minimum=None,
                 maximum=None, item_kind=None, item_enum=None, min_items=None,
                 pattern=None, min_len=None, max_len=None, default=None,
                 nullable=False):
        self.name = name
        self.kind = kind
        self.required = required
        self.enum = enum
        self.minimum = minimum
        self.maximum = maximum
        self.item_kind = item_kind
        self.item_enum = item_enum
        self.min_items = min_items
        self.pattern = pattern
        self.min_len = min_len
        self.max_len = max_len
        self.default = default
        self.nullable = nullable


def _check_scalar(kind, value):
    if kind == "string":
        return isinstance(value, str)
    if kind == "int":
        return isinstance(value, int) and not isinstance(value, bool)
    if kind == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if kind == "bool":
        return isinstance(value, bool)
    if kind == "date":
        return parse_date(value) is not None
    if kind == "datetime":
        return parse_datetime(value) is not None
    return True


def validate_body(body, fields):
    """Validate `body` against `fields`, in declaration order.

    Returns a dict of the accepted values (with defaults filled in for absent
    optional fields).
    """
    out = {}
    for f in fields:
        present = f.name in body and body[f.name] is not None
        if not present:
            if f.required:
                if f.name in body and body[f.name] is None and f.nullable:
                    out[f.name] = None
                    continue
                bad()
            out[f.name] = f.default
            continue
        value = body[f.name]
        if f.kind == "array":
            if not isinstance(value, list):
                bad()
            if f.min_items is not None and len(value) < f.min_items:
                bad()
            for item in value:
                if f.item_kind and not _check_scalar(f.item_kind, item):
                    bad()
                if f.item_enum is not None and item not in f.item_enum:
                    bad()
            out[f.name] = list(value)
            continue
        if f.kind == "enum":
            if not isinstance(value, str) or value not in f.enum:
                bad()
            out[f.name] = value
            continue
        if not _check_scalar(f.kind, value):
            bad()
        if f.kind in ("int", "number"):
            dec = to_decimal(value)
            if dec is None:
                bad()
            if f.minimum is not None and dec < Decimal(str(f.minimum)):
                bad()
            if f.maximum is not None and dec > Decimal(str(f.maximum)):
                bad()
        if f.kind == "string":
            if f.pattern is not None and not re.match(f.pattern, value):
                bad()
            if f.min_len is not None and len(value) < f.min_len:
                bad()
            if f.max_len is not None and len(value) > f.max_len:
                bad()
        out[f.name] = value
    return out
