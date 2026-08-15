"""Auth middleware: X-User-ID / X-User-Role headers and role gating."""
from functools import wraps

from flask import g, request

from errors import raise_err, ERR_UNAUTHENTICATED, ERR_FORBIDDEN

ROLES = {
    "EOCManager",
    "SiteLead",
    "IntakeStaff",
    "OutreachWorker",
    "MedicalResponder",
    "TransportCoordinator",
}

ALL_ROLES = tuple(sorted(ROLES))


def require_roles(*roles):
    allowed = set(roles) if roles else ROLES

    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            uid = request.headers.get("X-User-ID")
            role = request.headers.get("X-User-Role")
            if not uid or not role or role not in ROLES:
                raise_err(
                    ERR_UNAUTHENTICATED,
                    "Missing or invalid X-User-ID / X-User-Role headers",
                )
            if role not in allowed:
                raise_err(
                    ERR_FORBIDDEN,
                    f"Role {role} is not authorized for this endpoint",
                )
            g.user_id = uid
            g.user_role = role
            return fn(*args, **kwargs)

        return wrapper

    return deco
