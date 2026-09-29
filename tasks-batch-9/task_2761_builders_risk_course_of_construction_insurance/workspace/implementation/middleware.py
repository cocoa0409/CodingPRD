"""Header authentication, endpoint role authorisation, request-body schema helpers,
pagination and filter parsing. Evaluation order follows PRD 2.11."""
from decimal import Decimal, InvalidOperation

from flask import request

from enums import ROLES
from errors import ApiError
from util import parse_dt


# ---------------------------------------------------------------- auth (steps 1-2)

def authenticate(*allowed_roles):
    """Step 1: both headers present and X-User-Role recognised. Step 2: role authorised."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", "Missing or unrecognised authentication headers.")
    if role not in allowed_roles:
        raise ApiError(
            "ERR_UNAUTHORIZED", "Role %s is not authorised for this operation." % role
        )
    return user_id, role


# ---------------------------------------------------------------- body access

def body():
    if not request.data:
        return {}
    payload = request.get_json(silent=True)
    if payload is None:
        raise ApiError("ERR_INVALID_REQUEST", "Request body is not valid JSON.")
    if not isinstance(payload, dict):
        raise ApiError("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return payload


def _bad(field, why):
    raise ApiError("ERR_INVALID_REQUEST", "Field '%s' %s." % (field, why))


def present(payload, field):
    return field in payload and payload[field] is not None


def get_str(payload, field, required=True, default=None):
    if not present(payload, field):
        if required:
            _bad(field, "is required")
        return default
    value = payload[field]
    if not isinstance(value, str) or value == "":
        _bad(field, "must be a non-empty string")
    return value


def get_enum(payload, field, allowed, required=True, default=None):
    if not present(payload, field):
        if required:
            _bad(field, "is required")
        return default
    value = payload[field]
    if not isinstance(value, str) or value not in allowed:
        _bad(field, "must be one of %s" % ", ".join(allowed))
    return value


def get_int(payload, field, required=True, default=None, minimum=None, maximum=None):
    if not present(payload, field):
        if required:
            _bad(field, "is required")
        return default
    value = payload[field]
    if isinstance(value, bool) or not isinstance(value, int):
        _bad(field, "must be an integer")
    if minimum is not None and value < minimum:
        _bad(field, "must be >= %s" % minimum)
    if maximum is not None and value > maximum:
        _bad(field, "must be <= %s" % maximum)
    return value


def get_bool(payload, field, required=False, default=False):
    if not present(payload, field):
        if required:
            _bad(field, "is required")
        return default
    value = payload[field]
    if not isinstance(value, bool):
        _bad(field, "must be a boolean")
    return value


def get_number(payload, field, required=True, default=None, minimum=None, maximum=None,
               max_decimals=None, minimum_exclusive=None):
    if not present(payload, field):
        if required:
            _bad(field, "is required")
        return default
    value = payload[field]
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        _bad(field, "must be a number")
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        _bad(field, "must be a number")
    if not number.is_finite():
        _bad(field, "must be a finite number")
    if minimum is not None and number < Decimal(str(minimum)):
        _bad(field, "must be >= %s" % minimum)
    if minimum_exclusive is not None and number <= Decimal(str(minimum_exclusive)):
        _bad(field, "must be > %s" % minimum_exclusive)
    if maximum is not None and number > Decimal(str(maximum)):
        _bad(field, "must be <= %s" % maximum)
    if max_decimals is not None and -number.as_tuple().exponent > max_decimals:
        _bad(field, "must carry at most %d decimal places" % max_decimals)
    return number


def get_dt(payload, field, required=True, default=None):
    if not present(payload, field):
        if required:
            _bad(field, "is required")
        return default
    try:
        return parse_dt(payload[field])
    except (ValueError, TypeError):
        _bad(field, "must be an ISO 8601 datetime")


# ---------------------------------------------------------------- pagination & filters

PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0


def _query_int(name, default, minimum, maximum=None):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise ApiError("ERR_INVALID_REQUEST", "Query parameter '%s' must be an integer." % name)
    if value < minimum or (maximum is not None and value > maximum):
        raise ApiError(
            "ERR_INVALID_REQUEST", "Query parameter '%s' is outside its accepted range." % name
        )
    return value


def pagination():
    limit = _query_int(
        "limit", PAGINATION_DEFAULT_LIMIT, PAGINATION_MIN_LIMIT, PAGINATION_MAX_LIMIT
    )
    offset = _query_int("offset", PAGINATION_DEFAULT_OFFSET, 0)
    return limit, offset


def filter_enum(name, allowed):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    if raw not in allowed:
        raise ApiError(
            "ERR_INVALID_REQUEST", "Query parameter '%s' has an unrecognised value." % name
        )
    return raw


def filter_str(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    return raw


def paginate(rows, limit, offset):
    return rows[offset:offset + limit], len(rows)
