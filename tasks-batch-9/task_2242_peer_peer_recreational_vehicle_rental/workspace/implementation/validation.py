"""Header authentication, payload-shape validation and pagination parsing.

Implements ladder steps 1-4 of PRD 2.8.
"""

import re
from decimal import Decimal, InvalidOperation

from flask import request

from errors import fail
from store import parse_date, parse_dt

ROLES = ("Owner", "Renter", "PlatformAdmin", "ClaimsAdjuster")

_INT_RE = re.compile(r"^-?\d+$")
_STATE_RE = re.compile(r"^[A-Z]{2}$")
_MONTH_DAY_RE = re.compile(r"^\d{2}-\d{2}$")


# ------------------------------------------------------------------- auth -----
def authenticate(allowed_roles):
    """Ladder steps 1-3."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or str(user_id).strip() == "":
        fail("ERR_UNAUTHENTICATED", "X-User-ID header is required.")
    if role is None or str(role).strip() == "":
        fail("ERR_UNAUTHENTICATED", "X-User-Role header is required.")
    if role not in ROLES:
        fail("ERR_UNAUTHENTICATED", "X-User-Role is not a recognised role.")
    if role not in allowed_roles:
        fail("ERR_FORBIDDEN_ROLE", "Role %s may not perform this operation." % role)
    return user_id, role


# --------------------------------------------------------------- body/query ---
def body():
    if not request.data:
        return {}
    payload = request.get_json(silent=True)
    if payload is None:
        fail("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    if not isinstance(payload, dict):
        fail("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return payload


def pagination():
    limit, offset = 10, 0
    if "limit" in request.args:
        raw = request.args.get("limit")
        if raw is None or not _INT_RE.match(raw.strip()):
            fail("ERR_INVALID_REQUEST", "limit must be an integer.")
        limit = int(raw)
        if limit < 1 or limit > 100:
            fail("ERR_INVALID_REQUEST", "limit must be between 1 and 100.")
    if "offset" in request.args:
        raw = request.args.get("offset")
        if raw is None or not _INT_RE.match(raw.strip()):
            fail("ERR_INVALID_REQUEST", "offset must be an integer.")
        offset = int(raw)
        if offset < 0:
            fail("ERR_INVALID_REQUEST", "offset must not be negative.")
    return limit, offset


def query_enum(name, allowed):
    if name not in request.args:
        return None
    value = request.args.get(name)
    if value not in allowed:
        fail("ERR_INVALID_REQUEST", "%s is not a valid value for %s." % (value, name))
    return value


def query_str(name):
    if name not in request.args:
        return None
    return request.args.get(name)


def query_date(name):
    if name not in request.args:
        return None
    value = request.args.get(name)
    if parse_date(value) is None:
        fail("ERR_INVALID_REQUEST", "%s must be a YYYY-MM-DD date." % name)
    return value


# ------------------------------------------------------------ field readers ---
def _missing(data, name, required, default):
    if name not in data or data[name] is None:
        if required:
            fail("ERR_INVALID_REQUEST", "%s is required." % name)
        return True, default
    return False, None


def get_str(data, name, min_len=1, max_len=None, required=True, default=None):
    absent, fallback = _missing(data, name, required, default)
    if absent:
        return fallback
    value = data[name]
    if not isinstance(value, str):
        fail("ERR_INVALID_REQUEST", "%s must be a string." % name)
    if min_len is not None and len(value) < min_len:
        fail("ERR_INVALID_REQUEST", "%s must be at least %d characters." % (name, min_len))
    if max_len is not None and len(value) > max_len:
        fail("ERR_INVALID_REQUEST", "%s must be at most %d characters." % (name, max_len))
    return value


def get_int(data, name, min_v=None, max_v=None, required=True, default=None):
    absent, fallback = _missing(data, name, required, default)
    if absent:
        return fallback
    value = data[name]
    if isinstance(value, bool) or not isinstance(value, int):
        fail("ERR_INVALID_REQUEST", "%s must be an integer." % name)
    if min_v is not None and value < min_v:
        fail("ERR_INVALID_REQUEST", "%s must be at least %d." % (name, min_v))
    if max_v is not None and value > max_v:
        fail("ERR_INVALID_REQUEST", "%s must be at most %d." % (name, max_v))
    return value


def get_bool(data, name, required=True, default=None):
    absent, fallback = _missing(data, name, required, default)
    if absent:
        return fallback
    value = data[name]
    if not isinstance(value, bool):
        fail("ERR_INVALID_REQUEST", "%s must be a boolean." % name)
    return value


def get_enum(data, name, allowed, required=True, default=None):
    absent, fallback = _missing(data, name, required, default)
    if absent:
        return fallback
    value = data[name]
    if not isinstance(value, str) or value not in allowed:
        fail("ERR_INVALID_REQUEST", "%s must be one of %s." % (name, ", ".join(allowed)))
    return value


def get_tenth(data, name, min_v=None, required=True, default=None):
    """A number carried to one decimal place (a multiple of 0.1)."""
    absent, fallback = _missing(data, name, required, default)
    if absent:
        return fallback if not isinstance(fallback, (int, float)) else Decimal(str(fallback))
    value = data[name]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        fail("ERR_INVALID_REQUEST", "%s must be a number." % name)
    try:
        dec = Decimal(str(value))
    except InvalidOperation:
        fail("ERR_INVALID_REQUEST", "%s must be a number." % name)
    dec = dec.normalize()
    if dec == 0:
        dec = Decimal("0")
    if -dec.as_tuple().exponent > 1:
        fail("ERR_INVALID_REQUEST", "%s must be a multiple of 0.1." % name)
    if min_v is not None and dec < Decimal(str(min_v)):
        fail("ERR_INVALID_REQUEST", "%s must be at least %s." % (name, min_v))
    return dec


def get_date(data, name, required=True, default=None):
    absent, fallback = _missing(data, name, required, default)
    if absent:
        return fallback
    value = data[name]
    parsed = parse_date(value)
    if parsed is None:
        fail("ERR_INVALID_REQUEST", "%s must be a YYYY-MM-DD date." % name)
    return value


def get_datetime(data, name, required=True, default=None):
    """Returns the raw string; the caller keeps it verbatim for echo-back."""
    absent, fallback = _missing(data, name, required, default)
    if absent:
        return fallback
    value = data[name]
    parsed = parse_dt(value)
    if parsed is None:
        fail("ERR_INVALID_REQUEST", "%s must be an ISO 8601 instant." % name)
    return value


def get_str_array(data, name, allowed, non_empty=False, required=True, default=None):
    absent, fallback = _missing(data, name, required, default)
    if absent:
        return list(fallback) if fallback is not None else fallback
    value = data[name]
    if not isinstance(value, list):
        fail("ERR_INVALID_REQUEST", "%s must be an array." % name)
    for item in value:
        if not isinstance(item, str) or item not in allowed:
            fail("ERR_INVALID_REQUEST", "%s contains an unrecognised value." % name)
    if non_empty and not value:
        fail("ERR_INVALID_REQUEST", "%s must not be empty." % name)
    return list(value)


def get_state_code(data, name, required=True):
    value = get_str(data, name, min_len=2, max_len=2, required=required)
    if value is None:
        return None
    if not _STATE_RE.match(value):
        fail("ERR_INVALID_REQUEST", "%s must be exactly two uppercase letters." % name)
    return value


def get_month_day(data, name, required=True):
    value = get_str(data, name, min_len=5, max_len=5, required=required)
    if value is None:
        return None
    if not _MONTH_DAY_RE.match(value):
        fail("ERR_INVALID_REQUEST", "%s must match MM-DD." % name)
    return value


def get_email(data, name, required=True):
    value = get_str(data, name, min_len=1, max_len=None, required=required)
    if value is None:
        return None
    if "@" not in value:
        fail("ERR_INVALID_REQUEST", "%s must contain '@'." % name)
    return value


def forbid(data, name, reason):
    if name in data and data[name] is not None:
        fail("ERR_INVALID_REQUEST", reason)
