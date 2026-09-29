"""Request body / query parameter validation (PRD 2.3 and rule 3)."""

import re
from datetime import datetime, timezone
from decimal import Decimal

from errors import ApiError
from flask import request

_DT_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2})?(\.\d{1,9})?(Z|[+-]\d{2}:?\d{2})?$"
)

LIMIT_DEFAULT = 10
LIMIT_MIN = 1
LIMIT_MAX = 100
OFFSET_DEFAULT = 0


def invalid(message):
    raise ApiError("ERR_INVALID_REQUEST", message)


def parse_datetime(value, field="timestamp"):
    if not isinstance(value, str) or not _DT_RE.match(value.strip()):
        invalid("%s must be an ISO 8601 UTC timestamp" % field)
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        invalid("%s must be an ISO 8601 UTC timestamp" % field)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _coerce(name, kind, value, extra):
    if kind == "str":
        if not isinstance(value, str):
            invalid("%s must be a string" % name)
        return value
    if kind == "bool":
        if not isinstance(value, bool):
            invalid("%s must be a boolean" % name)
        return value
    if kind in ("money", "units"):
        if not _is_int(value):
            invalid("%s must be an integer" % name)
        if value < 0:
            invalid("%s must not be negative" % name)
        return value
    if kind == "posint":
        if not _is_int(value):
            invalid("%s must be an integer" % name)
        if value <= 0:
            invalid("%s must be greater than zero" % name)
        return value
    if kind == "qty":
        if not _is_int(value):
            invalid("%s must be an integer" % name)
        if value < 1:
            invalid("%s must be at least 1" % name)
        return value
    if kind == "signed":
        if not _is_int(value):
            invalid("%s must be an integer" % name)
        return value
    if kind == "hour":
        if not _is_int(value):
            invalid("%s must be an integer" % name)
        if value < 0 or value > 23:
            invalid("%s must be between 0 and 23" % name)
        return value
    if kind in ("pct", "pct45"):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            invalid("%s must be a number" % name)
        dec = Decimal(str(value))
        if dec < 0 or dec > 1:
            invalid("%s must be between 0 and 1 inclusive" % name)
        if kind == "pct45" and dec > Decimal("0.45"):
            invalid("%s must not exceed 0.45" % name)
        return dec
    if kind == "dt":
        return parse_datetime(value, name)
    if kind == "enum":
        if not isinstance(value, str) or value not in extra:
            invalid("%s must be one of %s" % (name, ", ".join(sorted(extra))))
        return value
    if kind == "strarray":
        if not isinstance(value, list):
            invalid("%s must be an array of strings" % name)
        for item in value:
            if not isinstance(item, str):
                invalid("%s must be an array of strings" % name)
        return list(value)
    invalid("unsupported field %s" % name)


def parse_body(spec):
    """spec: list of (name, kind, required[, extra]).  Unknown fields rejected."""
    raw = request.get_json(silent=True)
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        invalid("request body must be a JSON object")
    known = set(item[0] for item in spec)
    for key in raw:
        if key not in known:
            invalid("unknown field: %s" % key)
    out = {}
    for item in spec:
        name, kind, required = item[0], item[1], item[2]
        extra = item[3] if len(item) > 3 else None
        if name not in raw:
            if required:
                invalid("missing required field: %s" % name)
            continue
        value = raw[name]
        if value is None:
            if required:
                invalid("%s must not be null" % name)
            continue
        out[name] = _coerce(name, kind, value, extra)
    return out


def pagination():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit = LIMIT_DEFAULT
    offset = OFFSET_DEFAULT
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            invalid("limit must be an integer")
        if limit < LIMIT_MIN or limit > LIMIT_MAX:
            invalid("limit must be between %d and %d" % (LIMIT_MIN, LIMIT_MAX))
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            invalid("offset must be an integer")
        if offset < 0:
            invalid("offset must not be negative")
    return limit, offset


def q_str(name):
    return request.args.get(name)


def q_bool(name):
    raw = request.args.get(name)
    if raw is None:
        return None
    low = raw.strip().lower()
    if low == "true":
        return True
    if low == "false":
        return False
    return "__nomatch__"


def q_int(name):
    raw = request.args.get(name)
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return "__nomatch__"
