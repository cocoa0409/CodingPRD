"""Request body / query-string validation (ERR_INVALID_REQUEST, HTTP 422)."""
import re

from flask import request

from errors import fail

MISSING = object()


class Field:
    def __init__(self, name, ftype, required=False, default=MISSING, enum=None,
                 minimum=None, maximum=None, min_len=None, max_len=None, regex=None,
                 item_enum=None, item_type=None, distinct=False, non_empty=False):
        self.name = name
        self.ftype = ftype
        self.required = required
        self.default = default
        self.enum = enum
        self.minimum = minimum
        self.maximum = maximum
        self.min_len = min_len
        self.max_len = max_len
        self.regex = regex
        self.item_enum = item_enum
        self.item_type = item_type
        self.distinct = distinct
        self.non_empty = non_empty


def _type_ok(value, ftype):
    if ftype == "string":
        return isinstance(value, str)
    if ftype == "int":
        return isinstance(value, int) and not isinstance(value, bool)
    if ftype == "bool":
        return isinstance(value, bool)
    if ftype == "array":
        return isinstance(value, list)
    if ftype == "object":
        return isinstance(value, dict)
    return True


def body_or_none():
    """Return the parsed JSON body, or None when no body was sent."""
    raw = request.get_data(cache=True)
    if raw is None or len(raw.strip()) == 0:
        return None
    try:
        parsed = request.get_json(force=True, silent=False)
    except Exception:
        fail("ERR_INVALID_REQUEST", "Request body is not valid JSON.")
    return parsed


def no_body():
    """Endpoints that declare no input accept an absent, empty or `{}` body only."""
    parsed = body_or_none()
    if parsed is None:
        return {}
    if parsed == {} or parsed is None:
        return {}
    if not isinstance(parsed, dict):
        fail("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    if parsed:
        fail("ERR_INVALID_REQUEST", "Unknown field: %s" % sorted(parsed.keys())[0])
    return {}


def read_body():
    parsed = body_or_none()
    if parsed is None:
        fail("ERR_INVALID_REQUEST", "A JSON object body is required.")
    if not isinstance(parsed, dict):
        fail("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return parsed


def validate(body, fields):
    """Validate `body` against `fields`; returns the cleaned value dict."""
    known = {f.name for f in fields}
    for key in body.keys():
        if key not in known:
            fail("ERR_INVALID_REQUEST", "Unknown field: %s" % key)
    out = {}
    for f in fields:
        if f.name not in body:
            if f.required:
                fail("ERR_INVALID_REQUEST", "Missing required field: %s" % f.name)
            if f.default is not MISSING:
                out[f.name] = f.default
            continue
        value = body[f.name]
        if value is None:
            fail("ERR_INVALID_REQUEST", "Field %s must not be null." % f.name)
        if not _type_ok(value, f.ftype):
            fail("ERR_INVALID_REQUEST", "Field %s has the wrong type." % f.name)
        if f.enum is not None and value not in f.enum:
            fail("ERR_INVALID_REQUEST", "Field %s must be one of %s." % (f.name, ", ".join(map(str, f.enum))))
        if f.ftype == "int":
            if f.minimum is not None and value < f.minimum:
                fail("ERR_INVALID_REQUEST", "Field %s must be >= %s." % (f.name, f.minimum))
            if f.maximum is not None and value > f.maximum:
                fail("ERR_INVALID_REQUEST", "Field %s must be <= %s." % (f.name, f.maximum))
        if f.ftype == "string":
            if f.min_len is not None and len(value) < f.min_len:
                fail("ERR_INVALID_REQUEST", "Field %s is too short." % f.name)
            if f.max_len is not None and len(value) > f.max_len:
                fail("ERR_INVALID_REQUEST", "Field %s is too long." % f.name)
            if f.regex is not None and not re.fullmatch(f.regex, value):
                fail("ERR_INVALID_REQUEST", "Field %s is malformed." % f.name)
        if f.ftype == "array":
            if f.non_empty and len(value) == 0:
                fail("ERR_INVALID_REQUEST", "Field %s must not be empty." % f.name)
            for item in value:
                if f.item_type is not None and not _type_ok(item, f.item_type):
                    fail("ERR_INVALID_REQUEST", "Field %s contains an item of the wrong type." % f.name)
                if f.item_enum is not None and item not in f.item_enum:
                    fail("ERR_INVALID_REQUEST", "Field %s contains an unsupported value." % f.name)
            if f.distinct and len(set(map(str, value))) != len(value):
                fail("ERR_INVALID_REQUEST", "Field %s must not contain duplicates." % f.name)
        out[f.name] = value
    return out


def pagination():
    """limit defaults to 10 (1..100); offset defaults to 0 (>= 0)."""
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    limit = 10
    offset = 0
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            fail("ERR_INVALID_REQUEST", "limit must be an integer.")
        if limit < 1 or limit > 100:
            fail("ERR_INVALID_REQUEST", "limit must be between 1 and 100.")
    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            fail("ERR_INVALID_REQUEST", "offset must be an integer.")
        if offset < 0:
            fail("ERR_INVALID_REQUEST", "offset must be 0 or greater.")
    return limit, offset


def paginate(records, limit, offset):
    return records[offset:offset + limit]
