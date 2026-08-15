"""Auth header extraction, role checking, and request-body field helpers."""
from flask import request

from errors import (
    ApiError,
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
    ERR_FORBIDDEN_FOR_ROLE,
    ERR_INVALID_REQUEST,
)
from util import parse_dt, parse_date, fmt_dt, fmt_date

ROLES = {"MeterOpsAdmin", "Dispatcher", "FieldTechnician", "BillingLiaison", "Investigator"}
ALL_ROLES = ("MeterOpsAdmin", "Dispatcher", "FieldTechnician", "BillingLiaison", "Investigator")


def auth_context():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if uid is None or not uid.strip() or role is None or role not in ROLES:
        raise ApiError(
            ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            "X-User-ID and X-User-Role headers must be present and well-formed",
            400,
        )
    return uid, role


def require_roles(*roles):
    uid, role = auth_context()
    if role not in roles:
        raise ApiError(ERR_FORBIDDEN_FOR_ROLE, "Role is not authorized for this operation", 403)
    return uid, role


def body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError(ERR_INVALID_REQUEST, "Request body must be a JSON object", 400)
    return data


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def req_str(data, field):
    v = data.get(field)
    if v is None or not isinstance(v, str) or v == "":
        raise ApiError(ERR_INVALID_REQUEST, f"{field} is required and must be a string", 400)
    return v


def opt_str(data, field, default=None):
    v = data.get(field)
    if v is None:
        return default
    if not isinstance(v, str):
        raise ApiError(ERR_INVALID_REQUEST, f"{field} must be a string", 400)
    return v


def req_enum(data, field, allowed):
    v = data.get(field)
    if v is None or v not in allowed:
        raise ApiError(
            ERR_INVALID_REQUEST, f"{field} is required and must be one of {sorted(allowed)}", 400
        )
    return v


def opt_enum(data, field, allowed, default=None):
    v = data.get(field)
    if v is None:
        return default
    if v not in allowed:
        raise ApiError(ERR_INVALID_REQUEST, f"{field} must be one of {sorted(allowed)}", 400)
    return v


def req_int(data, field, minimum=None):
    v = data.get(field)
    if _is_int(v):
        iv = v
    elif isinstance(v, float) and v.is_integer():
        iv = int(v)
    else:
        raise ApiError(ERR_INVALID_REQUEST, f"{field} is required and must be an integer", 400)
    if minimum is not None and iv < minimum:
        raise ApiError(ERR_INVALID_REQUEST, f"{field} must be >= {minimum}", 400)
    return iv


def opt_bool(data, field, default=False):
    v = data.get(field)
    if v is None:
        return default
    if not isinstance(v, bool):
        raise ApiError(ERR_INVALID_REQUEST, f"{field} must be a boolean", 400)
    return v


def req_dt(data, field):
    """Required ISO datetime field; returns normalized ISO-ms string."""
    v = data.get(field)
    if v is None:
        raise ApiError(ERR_INVALID_REQUEST, f"{field} is required", 400)
    try:
        return fmt_dt(parse_dt(v))
    except (ValueError, TypeError):
        raise ApiError(ERR_INVALID_REQUEST, f"{field} must be an ISO 8601 datetime", 400)


def req_date(data, field):
    """Required YYYY-MM-DD date field; returns normalized string."""
    v = data.get(field)
    if v is None:
        raise ApiError(ERR_INVALID_REQUEST, f"{field} is required", 400)
    try:
        return fmt_date(parse_date(v))
    except (ValueError, TypeError):
        raise ApiError(ERR_INVALID_REQUEST, f"{field} must be a YYYY-MM-DD date", 400)
