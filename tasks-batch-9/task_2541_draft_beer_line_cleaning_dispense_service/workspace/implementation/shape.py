"""Step 4 of the ladder: request shape. Unknown/absent/mistyped/out-of-range input."""
from decimal import Decimal

from flask import request

from common import (D, PAGE_LIMIT_DEFAULT, PAGE_LIMIT_MAX, PAGE_LIMIT_MIN,
                    PAGE_OFFSET_DEFAULT, PAGE_OFFSET_MIN, parse_date, parse_dt)
from errors import raise_error


def bad(message):
    raise_error("ERR_INVALID_REQUEST", message)


class Field(object):
    def __init__(self, name, kind, required=False, nullable=False, values=None,
                 min_value=None, max_value=None, gt=None, ge=None, le=None,
                 allowed=None, max_len=None, min_len=1):
        self.name = name
        self.kind = kind
        self.required = required
        self.nullable = nullable
        self.values = values
        self.min_value = min_value
        self.max_value = max_value
        self.gt = gt
        self.ge = ge
        self.le = le
        self.allowed = allowed
        self.max_len = max_len
        self.min_len = min_len


def F(*args, **kwargs):
    return Field(*args, **kwargs)


def raw_body():
    """The JSON body as a dict. Absent bodies are treated as an empty object."""
    if not request.data:
        return {}
    try:
        payload = request.get_json(force=True, silent=False)
    except Exception:
        bad("Request body is not valid JSON.")
        return {}
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        bad("Request body must be a JSON object.")
    return payload


def _coerce(field, value):
    kind = field.kind
    if kind in ("str", "id"):
        if not isinstance(value, str):
            bad("Field '%s' must be a string." % field.name)
        text = value
        if len(text) < field.min_len:
            bad("Field '%s' must not be empty." % field.name)
        if field.max_len is not None and len(text) > field.max_len:
            bad("Field '%s' exceeds its maximum length." % field.name)
        return text
    if kind == "enum":
        if not isinstance(value, str):
            bad("Field '%s' must be a string." % field.name)
        if value not in field.values:
            bad("Field '%s' is not a member of the declared set." % field.name)
        return value
    if kind == "bool":
        if not isinstance(value, bool):
            bad("Field '%s' must be a boolean." % field.name)
        return value
    if kind == "int":
        if isinstance(value, bool) or not isinstance(value, int):
            bad("Field '%s' must be an integer." % field.name)
        _range_check(field, D(value))
        return value
    if kind == "num":
        if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
            bad("Field '%s' must be a number." % field.name)
        dec = D(value)
        if field.allowed is not None and dec not in field.allowed:
            bad("Field '%s' is not a member of the declared set." % field.name)
        _range_check(field, dec)
        return dec
    if kind == "date":
        parsed = parse_date(value) if isinstance(value, str) else None
        if parsed is None:
            bad("Field '%s' must be a YYYY-MM-DD date." % field.name)
        return parsed
    if kind == "datetime":
        parsed = parse_dt(value) if isinstance(value, str) else None
        if parsed is None:
            bad("Field '%s' must be an ISO 8601 UTC timestamp." % field.name)
        return parsed
    bad("Field '%s' could not be interpreted." % field.name)


def _range_check(field, dec):
    if field.min_value is not None and dec < D(field.min_value):
        bad("Field '%s' is below its minimum." % field.name)
    if field.max_value is not None and dec > D(field.max_value):
        bad("Field '%s' is above its maximum." % field.name)
    if field.gt is not None and dec <= D(field.gt):
        bad("Field '%s' must be greater than %s." % (field.name, field.gt))
    if field.ge is not None and dec < D(field.ge):
        bad("Field '%s' must be at least %s." % (field.name, field.ge))
    if field.le is not None and dec > D(field.le):
        bad("Field '%s' must be at most %s." % (field.name, field.le))


def parse_body(fields):
    """Validate the body against `fields`; rejects unknown members outright."""
    payload = raw_body()
    declared = set(f.name for f in fields)
    for key in payload.keys():
        if key not in declared:
            bad("Unknown field '%s' in request body." % key)
    out = {}
    for field in fields:
        if field.name not in payload:
            if field.required:
                bad("Field '%s' is required." % field.name)
            out[field.name] = None
            continue
        value = payload[field.name]
        if value is None:
            if field.nullable:
                out[field.name] = None
                continue
            bad("Field '%s' must not be null." % field.name)
        out[field.name] = _coerce(field, value)
    out["_present"] = set(payload.keys())
    return out


# ------------------------------------------------------------------- query input

def parse_pagination():
    limit = _query_int("limit", PAGE_LIMIT_DEFAULT, PAGE_LIMIT_MIN, PAGE_LIMIT_MAX)
    offset = _query_int("offset", PAGE_OFFSET_DEFAULT, PAGE_OFFSET_MIN, None)
    return limit, offset


def _query_int(name, default, minimum, maximum):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        bad("Query parameter '%s' must be an integer." % name)
        return default
    if str(value) != raw.strip():
        bad("Query parameter '%s' must be an integer." % name)
    if minimum is not None and value < minimum:
        bad("Query parameter '%s' is out of range." % name)
    if maximum is not None and value > maximum:
        bad("Query parameter '%s' is out of range." % name)
    return value


def query_enum(name, values):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    if raw not in values:
        bad("Query parameter '%s' is not a member of the declared set." % name)
    return raw


def query_bool(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    if raw == "true":
        return True
    if raw == "false":
        return False
    bad("Query parameter '%s' must be true or false." % name)


def query_str(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    return raw


def paginate(rows, limit, offset):
    total = len(rows)
    return rows[offset:offset + limit], total
