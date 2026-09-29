"""Auth (ladder rungs 1-4), request-shape validation (rung 5) and pagination."""
from decimal import Decimal
from functools import wraps

from flask import request

from calc import D
from errors import fail
from store import ROLES, parse_date, parse_ts


# ------------------------------------------------------------------ rungs 1-2
def authenticate(allowed_roles):
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not user_id.strip() or not role or role not in ROLES:
        fail("ERR_UNAUTHENTICATED")
    if role not in allowed_roles:
        fail("ERR_ROLE_NOT_PERMITTED")
    return user_id, role


def endpoint(*allowed_roles):
    """Decorator: rung 1 then rung 2, then hand (user_id, role) to the view."""
    roles = set(allowed_roles)

    def decorator(view):
        @wraps(view)
        def wrapper(**kwargs):
            user_id, role = authenticate(roles)
            return view(user_id, role, **kwargs)
        return wrapper
    return decorator


# ------------------------------------------------------------------ rung 5
def get_body():
    if not request.data:
        return {}
    body = request.get_json(silent=True)
    if body is None or not isinstance(body, dict):
        fail("ERR_VALIDATION_FAILED", "Request body must be a JSON object.")
    return body


def _present(body, name):
    return name in body and body[name] is not None


def v_str(body, name, required=True, min_len=1, max_len=None, default=None):
    if not _present(body, name):
        if required:
            fail("ERR_VALIDATION_FAILED", "Field '%s' is required." % name)
        return default
    value = body[name]
    if not isinstance(value, str):
        fail("ERR_VALIDATION_FAILED", "Field '%s' must be a string." % name)
    if len(value) < min_len:
        fail("ERR_VALIDATION_FAILED", "Field '%s' is too short." % name)
    if max_len is not None and len(value) > max_len:
        fail("ERR_VALIDATION_FAILED", "Field '%s' is too long." % name)
    return value


def v_enum(body, name, allowed, required=True, default=None):
    if not _present(body, name):
        if required:
            fail("ERR_VALIDATION_FAILED", "Field '%s' is required." % name)
        return default
    value = body[name]
    if not isinstance(value, str) or value not in allowed:
        fail("ERR_VALIDATION_FAILED", "Field '%s' is not a declared member." % name)
    return value


def v_bool(body, name, required=False, default=None):
    if not _present(body, name):
        if required:
            fail("ERR_VALIDATION_FAILED", "Field '%s' is required." % name)
        return default
    value = body[name]
    if not isinstance(value, bool):
        fail("ERR_VALIDATION_FAILED", "Field '%s' must be a boolean." % name)
    return value


def v_num(body, name, required=True, gt=None, ge=None, lt=None, le=None, default=None):
    """Returns a Decimal (or the default) for a JSON number field."""
    if not _present(body, name):
        if required:
            fail("ERR_VALIDATION_FAILED", "Field '%s' is required." % name)
        return default
    value = body[name]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        fail("ERR_VALIDATION_FAILED", "Field '%s' must be a number." % name)
    dec = D(value)
    _range_check(name, dec, gt, ge, lt, le)
    return dec


def v_int(body, name, required=True, gt=None, ge=None, lt=None, le=None, default=None,
          choices=None):
    if not _present(body, name):
        if required:
            fail("ERR_VALIDATION_FAILED", "Field '%s' is required." % name)
        return default
    value = body[name]
    if isinstance(value, bool) or not isinstance(value, int):
        fail("ERR_VALIDATION_FAILED", "Field '%s' must be an integer." % name)
    _range_check(name, Decimal(value), gt, ge, lt, le)
    if choices is not None and value not in choices:
        fail("ERR_VALIDATION_FAILED", "Field '%s' is not an allowed value." % name)
    return value


def _range_check(name, dec, gt, ge, lt, le):
    if gt is not None and not dec > D(gt):
        fail("ERR_VALIDATION_FAILED", "Field '%s' is out of range." % name)
    if ge is not None and not dec >= D(ge):
        fail("ERR_VALIDATION_FAILED", "Field '%s' is out of range." % name)
    if lt is not None and not dec < D(lt):
        fail("ERR_VALIDATION_FAILED", "Field '%s' is out of range." % name)
    if le is not None and not dec <= D(le):
        fail("ERR_VALIDATION_FAILED", "Field '%s' is out of range." % name)


def v_ts(body, name, required=True, default=None):
    if not _present(body, name):
        if required:
            fail("ERR_VALIDATION_FAILED", "Field '%s' is required." % name)
        return default
    parsed = parse_ts(body[name])
    if parsed is None:
        fail("ERR_VALIDATION_FAILED", "Field '%s' must be an RFC3339 UTC timestamp." % name)
    return parsed


def v_date(body, name, required=True, default=None):
    """A PRD `_date` field: a calendar date, not an instant.

    The PRD names instants with an `_at` suffix and dates with a `_date`
    suffix, so a `_date` field carries a plain calendar date (`YYYY-MM-DD`).
    A full RFC 3339 UTC instant is accepted too and truncated to its date.
    """
    if not _present(body, name):
        if required:
            fail("ERR_VALIDATION_FAILED", "Field '%s' is required." % name)
        return default
    parsed = parse_date(body[name])
    if parsed is None:
        fail("ERR_VALIDATION_FAILED", "Field '%s' must be a calendar date." % name)
    return parsed


def v_id(body, name, required=True, default=None):
    if not _present(body, name):
        if required:
            fail("ERR_VALIDATION_FAILED", "Field '%s' is required." % name)
        return default
    value = body[name]
    if not isinstance(value, str) or not value:
        fail("ERR_VALIDATION_FAILED", "Field '%s' must be an id string." % name)
    return value


# ------------------------------------------------------------------ pagination
def pagination():
    limit = 10
    offset = 0
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is not None:
        limit = _positive_int("limit", raw_limit)
        if limit < 1 or limit > 100:
            fail("ERR_VALIDATION_FAILED", "limit must be between 1 and 100.")
    if raw_offset is not None:
        offset = _positive_int("offset", raw_offset)
        if offset < 0:
            fail("ERR_VALIDATION_FAILED", "offset may not be negative.")
    return limit, offset


def _positive_int(name, raw):
    text = raw.strip()
    if not text or not (text.lstrip("-").isdigit()):
        fail("ERR_VALIDATION_FAILED", "%s must be an integer." % name)
    return int(text)


def q_num(name, required=False, gt=None, ge=None, lt=None, le=None, default=None):
    raw = request.args.get(name)
    if raw is None or raw == "":
        if required:
            fail("ERR_VALIDATION_FAILED", "Query parameter '%s' is required." % name)
        return default
    try:
        dec = Decimal(raw.strip())
    except Exception:
        fail("ERR_VALIDATION_FAILED", "Query parameter '%s' must be numeric." % name)
    _range_check(name, dec, gt, ge, lt, le)
    return dec


def q_int(name, required=False, ge=None, le=None, default=None):
    raw = request.args.get(name)
    if raw is None or raw == "":
        if required:
            fail("ERR_VALIDATION_FAILED", "Query parameter '%s' is required." % name)
        return default
    text = raw.strip()
    if not text.lstrip("-").isdigit():
        fail("ERR_VALIDATION_FAILED", "Query parameter '%s' must be an integer." % name)
    value = int(text)
    _range_check(name, Decimal(value), None, ge, None, le)
    return value


def q_enum(name, allowed, required=False, default=None):
    raw = request.args.get(name)
    if raw is None or raw == "":
        if required:
            fail("ERR_VALIDATION_FAILED", "Query parameter '%s' is required." % name)
        return default
    if raw not in allowed:
        fail("ERR_VALIDATION_FAILED", "Query parameter '%s' is not a declared member." % name)
    return raw
