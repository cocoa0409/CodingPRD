"""Rungs 1-8 of the single ordered validation ladder (PRD §2.7).

Rung  1  headers present and non-empty            -> ERR_UNAUTHENTICATED (401)
Rung  2  role names one of the five roles         -> ERR_UNAUTHENTICATED (401)
Rung  3  role authorised for this endpoint        -> ERR_UNAUTHORIZED   (403)
Rung  4  ownership / segregation of duties        -> ERR_UNAUTHORIZED   (403)
Rung  5  pagination parameters                    -> ERR_VALIDATION     (400)
Rung  6  required body fields present, non-null   -> ERR_VALIDATION     (400)
Rung  7  types, numeric ranges, string formats    -> ERR_VALIDATION     (400)
Rung  8  enum membership, CLOSED body-field list  -> ERR_INVALID_ENUM   (400)
"""

from functools import wraps

from flask import request

from .constants import ENUM_ERROR_FIELD_LIST, ROLES
from .errors import fail
from . import numbers as N
from . import timeutil as T


# ---------------------------------------------------------------- rungs 1-3
def caller_role():
    return request.headers.get("X-User-Role")


def caller_id():
    return request.headers.get("X-User-ID")


def check_auth(allowed_roles):
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not user_id.strip() or not role or not role.strip():
        fail("ERR_UNAUTHENTICATED", "Both X-User-ID and X-User-Role are required.")
    if role not in ROLES:
        fail("ERR_UNAUTHENTICATED", "Unknown role %r." % role)
    if role not in allowed_roles:
        fail("ERR_UNAUTHORIZED", "Role %s may not call this endpoint." % role)


def endpoint(roles):
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            check_auth(roles)
            return fn(*args, **kwargs)
        return wrapper
    return decorator


# ------------------------------------------------------------------ rung 5
def pagination():
    """limit defaults to 10 (1..100); offset defaults to 0 (>= 0)."""
    limit = 10
    offset = 0
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is not None:
        limit = _int_param(raw_limit, "limit")
        if limit < 1 or limit > 100:
            fail("ERR_VALIDATION", "limit must be between 1 and 100.")
    if raw_offset is not None:
        offset = _int_param(raw_offset, "offset")
        if offset < 0:
            fail("ERR_VALIDATION", "offset must be at least 0.")
    return limit, offset


def _int_param(raw, name):
    text = raw.strip()
    if not text:
        fail("ERR_VALIDATION", "%s must be an integer." % name)
    negative = text.startswith("-")
    digits = text[1:] if negative else text
    if not digits.isdigit():
        fail("ERR_VALIDATION", "%s must be an integer." % name)
    return int(text)


def paginate(rows, limit, offset):
    return rows[offset:offset + limit]


def query_enum(name, members):
    """An out-of-range QUERY parameter is ERR_VALIDATION (§2.9) - by position."""
    value = request.args.get(name)
    if value is None:
        return None
    if value not in members:
        fail("ERR_VALIDATION", "Unsupported %s filter %r." % (name, value))
    return value


# ------------------------------------------------------------- rungs 6/7/8
class Field:
    def __init__(self, name, kind, required=False, members=None, minimum=None,
                 maximum=None, exclusive_min=None, exclusive_max=None):
        self.name = name
        self.kind = kind
        self.required = required
        self.members = members
        self.minimum = minimum
        self.maximum = maximum
        self.exclusive_min = exclusive_min
        self.exclusive_max = exclusive_max


def json_body():
    payload = request.get_json(silent=True)
    if payload is None:
        payload = {}
    if not isinstance(payload, dict):
        fail("ERR_VALIDATION", "The request body must be a JSON object.")
    return payload


def validate_body(fields, cross=None):
    """Run rungs 6, 7 and 8 over the request body in that exact order."""
    payload = json_body()

    # rung 6 - presence
    for field in fields:
        if field.required:
            if field.name not in payload or payload[field.name] is None:
                fail("ERR_VALIDATION", "Field %r is required." % field.name)

    # rung 7 - types, ranges, formats (enum fields must at least be strings)
    for field in fields:
        value = payload.get(field.name)
        if value is None:
            continue
        _check_type(field, value)
    if cross is not None:
        cross(payload)

    # rung 8 - enum membership, closed routing list
    for field in fields:
        value = payload.get(field.name)
        if value is None or field.kind != "enum":
            continue
        if value not in field.members:
            _enum_failure(field.name, value)

    return payload


def _enum_failure(name, value):
    if name in ENUM_ERROR_FIELD_LIST:
        fail("ERR_INVALID_ENUM", "%r is not a valid %s." % (value, name))
    fail("ERR_VALIDATION", "%r is not a valid %s." % (value, name))


def _check_type(field, value):
    name = field.name
    kind = field.kind
    if kind == "string" or kind == "enum":
        if not isinstance(value, str):
            fail("ERR_VALIDATION", "%s must be a string." % name)
        return
    if kind == "bool":
        if not isinstance(value, bool):
            fail("ERR_VALIDATION", "%s must be a boolean." % name)
        return
    if kind == "int":
        if not N.is_int(value):
            fail("ERR_VALIDATION", "%s must be an integer." % name)
        _check_range(field, value)
        return
    if kind == "number":
        if not N.is_number(value):
            fail("ERR_VALIDATION", "%s must be a number." % name)
        _check_range(field, value)
        return
    if kind == "date":
        if not isinstance(value, str) or T.parse_date(value) is None:
            fail("ERR_VALIDATION", "%s must be a YYYY-MM-DD date." % name)
        return
    if kind == "instant":
        if not isinstance(value, str) or T.parse_instant(value) is None:
            fail("ERR_VALIDATION", "%s must be an ISO 8601 instant." % name)
        return
    if kind == "string_array":
        if not isinstance(value, list) or any(not isinstance(x, str) for x in value):
            fail("ERR_VALIDATION", "%s must be an array of strings." % name)
        return
    if kind == "array":
        if not isinstance(value, list):
            fail("ERR_VALIDATION", "%s must be an array." % name)
        return
    raise AssertionError("unknown field kind %r" % kind)


def _check_range(field, value):
    name = field.name
    if field.exclusive_min is not None and not value > field.exclusive_min:
        fail("ERR_VALIDATION", "%s must be greater than %s." % (name, field.exclusive_min))
    if field.minimum is not None and value < field.minimum:
        fail("ERR_VALIDATION", "%s must be at least %s." % (name, field.minimum))
    if field.maximum is not None and value > field.maximum:
        fail("ERR_VALIDATION", "%s must be at most %s." % (name, field.maximum))
    if field.exclusive_max is not None and not value < field.exclusive_max:
        fail("ERR_VALIDATION", "%s must be less than %s." % (name, field.exclusive_max))
