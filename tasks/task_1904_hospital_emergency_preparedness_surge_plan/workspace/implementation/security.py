"""Authentication (priority 1) and role authorization (priority 2)."""

from functools import wraps

from flask import g, request

from errors import ApiError

ALL_ROLES = {
    "EmergencyManager",
    "IncidentCommander",
    "PlanningChief",
    "LogisticsChief",
    "PublicInformationOfficer",
    "LiaisonOfficer",
    "HospitalAdministrator",
    "OnCallStaff",
    "PlatformAdmin",
}


def authenticate():
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ALL_ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", 401,
                       "missing or invalid X-User-ID / X-User-Role headers")
    return user_id, role


def authorize(roles):
    """Decorator: authenticate, then check the role is in the endpoint list."""
    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_id, role = authenticate()
            if role not in roles:
                raise ApiError("ERR_FORBIDDEN_ROLE", 403,
                               "role %s is not authorized for this endpoint" % role)
            g.user_id = user_id
            g.user_role = role
            return fn(*args, **kwargs)
        return wrapper
    return deco
