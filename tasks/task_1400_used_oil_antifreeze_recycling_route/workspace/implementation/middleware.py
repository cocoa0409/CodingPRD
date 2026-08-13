"""Authentication, RBAC, and request-body helpers.

Auth headers (PRD §2.1): every request carries X-User-ID and X-User-Role.
The seven recognized roles are RoutePlanner, Driver, LabTech, SettlementClerk,
EHSOfficer, Regulator, TankInstaller. A missing, empty, or unrecognized header
is rejected with ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER (400). A
well-known role not permitted on an endpoint is rejected with
ERR_INSUFFICIENT_PERMISSIONS (403).

Driver is entity-backed: X-User-ID is the acting Driver entity's id, and
driver-executed mutations on a route compare the route's driver_id against it.
"""

import re
from functools import wraps

from flask import request

from errors import (
    ApiError,
    ERR_INSUFFICIENT_PERMISSIONS,
    ERR_INVALID_ENUM,
    ERR_INVALID_REQUEST,
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
)

ROLES = {
    "RoutePlanner",
    "Driver",
    "LabTech",
    "SettlementClerk",
    "EHSOfficer",
    "Regulator",
    "TankInstaller",
}


def current_user():
    """Validate the auth headers. Returns (user_id, role)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if (
        user_id is None
        or role is None
        or not str(user_id).strip()
        or not str(role).strip()
        or role not in ROLES
    ):
        raise ApiError(
            ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            "X-User-ID and X-User-Role headers must be present and well-formed",
            400,
        )
    return user_id, role


def require_roles(*roles):
    """Decorator: header check (priority 1) then role authorization (priority 2)."""

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_id, role = current_user()
            if role not in roles:
                raise ApiError(
                    ERR_INSUFFICIENT_PERMISSIONS,
                    f"Role {role} is not permitted to invoke this endpoint",
                    403,
                )
            request.user_id = user_id
            request.user_role = role
            return fn(*args, **kwargs)

        return wrapper

    return decorator


# ---------------------------------------------------------------------------
# Body parsing / field validators
# ---------------------------------------------------------------------------


def get_body(required=True):
    """Return the JSON request body as a dict; 400 when missing/malformed."""
    if request.data is None or request.data == b"":
        if required:
            raise ApiError(ERR_INVALID_REQUEST, "Request body must be a JSON object", 400)
        return {}
    data = request.get_json(silent=True)
    if data is None or not isinstance(data, dict):
        raise ApiError(ERR_INVALID_REQUEST, "Request body must be a JSON object", 400)
    return data


def _missing(body, field):
    return field not in body or body[field] is None


def req_str(body, field):
    if _missing(body, field) or not isinstance(body[field], str) or not body[field].strip():
        raise ApiError(ERR_INVALID_REQUEST, f"Missing or invalid required field: {field}", 400)
    return body[field]


def opt_str(body, field, default=None):
    if _missing(body, field):
        return default
    if not isinstance(body[field], str):
        raise ApiError(ERR_INVALID_REQUEST, f"Field must be a string: {field}", 400)
    return body[field]


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def req_int(body, field, minimum=None, maximum=None):
    if _missing(body, field) or not _is_int(body[field]):
        raise ApiError(ERR_INVALID_REQUEST, f"Missing or invalid required field: {field}", 400)
    v = body[field]
    if minimum is not None and v < minimum:
        raise ApiError(ERR_INVALID_REQUEST, f"Field {field} must be >= {minimum}", 400)
    if maximum is not None and v > maximum:
        raise ApiError(ERR_INVALID_REQUEST, f"Field {field} must be <= {maximum}", 400)
    return v


def opt_int(body, field, default=None, minimum=None, maximum=None):
    if _missing(body, field):
        return default
    return req_int(body, field, minimum=minimum, maximum=maximum)


def req_bool(body, field):
    if _missing(body, field) or not isinstance(body[field], bool):
        raise ApiError(ERR_INVALID_REQUEST, f"Missing or invalid required field: {field}", 400)
    return body[field]


def opt_bool(body, field, default=False):
    if _missing(body, field):
        return default
    if not isinstance(body[field], bool):
        raise ApiError(ERR_INVALID_REQUEST, f"Field must be a boolean: {field}", 400)
    return body[field]


def req_enum(body, field, allowed):
    if _missing(body, field) or not isinstance(body[field], str):
        raise ApiError(ERR_INVALID_REQUEST, f"Missing or invalid required field: {field}", 400)
    v = body[field]
    if v not in allowed:
        raise ApiError(ERR_INVALID_ENUM, f"Field {field} must be one of {sorted(allowed)}", 400)
    return v


def req_number(body, field, minimum=None, maximum=None):
    if _missing(body, field) or not isinstance(body[field], (int, float)) or isinstance(body[field], bool):
        raise ApiError(ERR_INVALID_REQUEST, f"Missing or invalid required field: {field}", 400)
    v = body[field]
    if minimum is not None and v < minimum:
        raise ApiError(ERR_INVALID_REQUEST, f"Field {field} must be >= {minimum}", 400)
    if maximum is not None and v > maximum:
        raise ApiError(ERR_INVALID_REQUEST, f"Field {field} must be <= {maximum}", 400)
    return v


_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def req_date(body, field):
    v = req_str(body, field)
    if not _DATE_RE.match(v):
        raise ApiError(ERR_INVALID_REQUEST, f"Field {field} must be an ISO date (YYYY-MM-DD)", 400)
    # Validate it is a real calendar date.
    from datetime import date as _date

    try:
        _date.fromisoformat(v)
    except ValueError:
        raise ApiError(ERR_INVALID_REQUEST, f"Field {field} must be an ISO date (YYYY-MM-DD)", 400)
    return v


def req_time_hhmm(body, field):
    v = req_str(body, field)
    if not _TIME_RE.match(v):
        raise ApiError(ERR_INVALID_REQUEST, f"Field {field} must be HH:MM 24h local time", 400)
    return v


def req_list(body, field):
    if _missing(body, field) or not isinstance(body[field], list):
        raise ApiError(ERR_INVALID_REQUEST, f"Missing or invalid required field: {field}", 400)
    return body[field]
