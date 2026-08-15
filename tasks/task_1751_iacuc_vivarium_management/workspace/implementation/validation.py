"""Auth middleware (PRD §2.1) and payload field validators (priority 1-3)."""
from flask import request

from db import parse_dt
from errors import (
    ApiError,
    ERR_UNAUTHENTICATED,
    ERR_FORBIDDEN,
    invalid_request,
)

ROLES = {
    "IacucAdministrator",
    "Investigator",
    "AnimalCareStaff",
    "AttendingVeterinarian",
    "FacilityManager",
    "BillingCoordinator",
    "TrainingCoordinator",
    "OccHealthNurse",
}


def authenticate():
    """Priority 1: X-User-ID and X-User-Role present; role is a declared role."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise ApiError(
            ERR_UNAUTHENTICATED,
            401,
            "Missing or malformed X-User-ID / X-User-Role headers",
        )
    return uid, role


def require_role(role, *allowed):
    """Priority 2: role permitted for this endpoint."""
    if role not in allowed:
        raise ApiError(ERR_FORBIDDEN, 403, "Role not permitted for this endpoint")


# ---------------------------------------------------------------------------
# Field validators -- all raise ERR_INVALID_REQUEST (400), priority 3.
# ---------------------------------------------------------------------------

def req_str(body, name):
    v = body.get(name)
    if not isinstance(v, str) or v == "":
        raise invalid_request(f"Field '{name}' is required and must be a string")
    return v


def opt_str(body, name, default=None):
    v = body.get(name, default)
    if v is None:
        return None
    if not isinstance(v, str):
        raise invalid_request(f"Field '{name}' must be a string")
    return v


def req_int(body, name, minimum=None):
    v = body.get(name)
    if isinstance(v, bool) or not isinstance(v, int):
        raise invalid_request(f"Field '{name}' is required and must be an integer")
    if minimum is not None and v < minimum:
        raise invalid_request(f"Field '{name}' must be >= {minimum}")
    return v


def opt_int(body, name, default=None, minimum=None):
    if name not in body or body.get(name) is None:
        return default
    return req_int(body, name, minimum=minimum)


def req_enum(body, name, allowed):
    v = body.get(name)
    if not isinstance(v, str) or v not in allowed:
        raise invalid_request(
            f"Field '{name}' must be one of {sorted(allowed)}"
        )
    return v


def req_dt(body, name):
    v = body.get(name)
    dt = parse_dt(v)
    if dt is None:
        raise invalid_request(f"Field '{name}' is required and must be an ISO 8601 datetime")
    return dt


def opt_dt(body, name, default=None):
    if name not in body or body.get(name) is None:
        return default
    return req_dt(body, name)
