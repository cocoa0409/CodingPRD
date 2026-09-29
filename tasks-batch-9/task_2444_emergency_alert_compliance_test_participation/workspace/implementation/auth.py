"""Auth headers, RBAC and ownership checks (PRD 2.1, ladder rungs 1/2/5)."""

import functools

from flask import g, request

from errors import ApiError

ROLES = ("ComplianceAdmin", "StationEngineer", "CertifyingOfficer", "FieldInspector")
ANY_ROLE = ROLES


def _authenticate(allowed_roles):
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise ApiError("ERR_MISSING_AUTH_HEADERS")
    if role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED")
    g.user_id = user_id
    g.user_role = role
    return user_id, role


def guard(*allowed_roles):
    """Decorator: rung 1 (401) then rung 2 (403) before anything else runs."""
    roles = tuple(allowed_roles) or ANY_ROLE

    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            _authenticate(roles)
            return fn(*args, **kwargs)

        return wrapper

    return decorator


def check_station_ownership(station):
    """Rung 5 (PRD 2.1 ownership checks)."""
    role = getattr(g, "user_role", None)
    user_id = getattr(g, "user_id", None)
    if role == "StationEngineer":
        if user_id not in (station.get("engineer_user_ids") or []):
            raise ApiError("ERR_ENGINEER_NOT_ASSIGNED")
    elif role == "CertifyingOfficer":
        if user_id != station.get("certification_officer_user_id"):
            raise ApiError("ERR_NOT_CERTIFYING_OFFICER")
