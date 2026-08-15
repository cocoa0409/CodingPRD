"""Auth middleware: X-User-ID / X-User-Role extraction and role checks."""

from functools import wraps

from flask import request

from errors import ApiError

ROLES = {"Recruiter", "TrainingCoordinator", "CheckAirman", "CrewScheduler", "Pilot", "SystemAdmin"}


def actor():
    """Validate the two auth headers; return (user_id, role)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", "Missing or unrecognized X-User-ID / X-User-Role headers")
    return user_id, role


def require_roles(*allowed):
    """Authenticate, then enforce endpoint role membership (SystemAdmin is NOT an
    implicit member; each endpoint table lists it explicitly where allowed)."""
    user_id, role = actor()
    if role not in allowed:
        raise ApiError("ERR_FORBIDDEN_ROLE", "Role %s is not authorized for this endpoint" % role)
    return user_id, role
