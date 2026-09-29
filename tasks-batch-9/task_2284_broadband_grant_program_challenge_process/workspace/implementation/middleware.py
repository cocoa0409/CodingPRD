"""Auth headers, request-body validation and pagination (PRD sections 2.1-2.3)."""

from decimal import Decimal, InvalidOperation

from flask import request

from db import parse_ts
from errors import ApiError

ROLES = (
    "ProgramAdmin",
    "EligibilityAnalyst",
    "Challenger",
    "Provider",
    "Subgrantee",
    "CapabilityReviewer",
    "ScoringOfficer",
    "AuditOfficer",
    "EnvironmentalReviewer",
)

USER_HEADER = "X-User-ID"
ROLE_HEADER = "X-User-Role"


def authenticate(*allowed_roles):
    """Priority 10 then 12: identity header, then role membership."""
    user_id = request.headers.get(USER_HEADER)
    if user_id is None or not str(user_id).strip():
        raise ApiError("ERR_UNAUTHENTICATED")
    role = request.headers.get(ROLE_HEADER)
    if role is None or role not in ROLES:
        raise ApiError("ERR_UNAUTHORIZED")
    if allowed_roles and role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED")
    return str(user_id), role


# ------------------------------------------------------------------ body i/o

def json_body():
    raw = request.get_data(cache=True)
    if raw is None or not raw.strip():
        return {}
    try:
        data = request.get_json(force=True, silent=False)
    except Exception:
        raise ApiError("ERR_INVALID_REQUEST", "Request body is not valid JSON.")
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return data


def _bad(field, why):
    raise ApiError("ERR_INVALID_REQUEST", "Field '%s' %s." % (field, why))


def _present(body, field, required):
    if field not in body or body.get(field) is None:
        if required:
            _bad(field, "is required")
        return False
    return True


def get_str(body, field, required=True, default=None, allow_blank=False):
    if not _present(body, field, required):
        return default
    value = body.get(field)
    if not isinstance(value, str):
        _bad(field, "must be a string")
    if not allow_blank and not value.strip():
        _bad(field, "must be a non-empty string")
    return value


def get_int(body, field, required=True, default=None, minimum=None, maximum=None):
    if not _present(body, field, required):
        return default
    value = body.get(field)
    if isinstance(value, bool) or not isinstance(value, int):
        _bad(field, "must be an integer")
    if minimum is not None and value < minimum:
        _bad(field, "must be >= %s" % minimum)
    if maximum is not None and value > maximum:
        _bad(field, "must be <= %s" % maximum)
    return value


def get_number(body, field, required=True, default=None, minimum=None, maximum=None):
    if not _present(body, field, required):
        return default
    value = body.get(field)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _bad(field, "must be a number")
    try:
        dec = Decimal(str(value))
    except InvalidOperation:
        _bad(field, "must be a number")
    if minimum is not None and dec < Decimal(str(minimum)):
        _bad(field, "must be >= %s" % minimum)
    if maximum is not None and dec > Decimal(str(maximum)):
        _bad(field, "must be <= %s" % maximum)
    return float(value)


def get_pct(body, field, required=True, default=None):
    return get_number(body, field, required=required, default=default, minimum=0, maximum=100)


def get_cents(body, field, required=True, default=None, positive=False):
    minimum = 1 if positive else 0
    return get_int(body, field, required=required, default=default, minimum=minimum)


def get_bool(body, field, required=False, default=None):
    if not _present(body, field, required):
        return default
    value = body.get(field)
    if not isinstance(value, bool):
        _bad(field, "must be a boolean")
    return value


def get_enum(body, field, allowed, required=True, default=None):
    if not _present(body, field, required):
        return default
    value = body.get(field)
    if not isinstance(value, str) or value not in allowed:
        _bad(field, "must be one of %s" % ", ".join(allowed))
    return value


def get_ts(body, field, required=True, default=None):
    """Returns (raw_string, datetime)."""
    if not _present(body, field, required):
        return default, None
    value = body.get(field)
    if not isinstance(value, str):
        _bad(field, "must be an ISO 8601 timestamp string")
    parsed = parse_ts(value)
    if parsed is None:
        _bad(field, "must be an ISO 8601 timestamp with an explicit UTC offset")
    return value, parsed


def get_id_list(body, field, required=True, default=None, allow_empty=True):
    if not _present(body, field, required):
        return default if default is not None else []
    value = body.get(field)
    if not isinstance(value, list):
        _bad(field, "must be an array of ids")
    for item in value:
        if not isinstance(item, str) or not item.strip():
            _bad(field, "must contain only non-empty string ids")
    if not allow_empty and not value:
        _bad(field, "must not be empty")
    return list(value)


# ---------------------------------------------------------------- pagination

def pagination():
    """Priority 16: limit in 1..100 (default 10), offset >= 0 (default 0)."""
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args:
        raw = args.get("limit")
        try:
            limit = int(str(raw).strip())
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_PAGINATION")
        if limit < 1 or limit > 100:
            raise ApiError("ERR_INVALID_PAGINATION")
    if "offset" in args:
        raw = args.get("offset")
        try:
            offset = int(str(raw).strip())
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_PAGINATION")
        if offset < 0:
            raise ApiError("ERR_INVALID_PAGINATION")
    return limit, offset
