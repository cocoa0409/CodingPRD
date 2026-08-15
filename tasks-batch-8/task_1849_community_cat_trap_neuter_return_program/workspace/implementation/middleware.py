"""Auth middleware (SCAFFOLD.yaml §1.4 priorities 1-2 / PRD §2.1).

Every request must carry X-User-ID and X-User-Role. The role must be one of
the five declared roles. Missing headers or an unknown role yield
ERR_UNAUTHENTICATED (401); an authenticated caller whose role is not listed
for the endpoint yields ERR_FORBIDDEN (403). Authentication is always
evaluated before authorization, and authorization before any resource lookup.

Identity semantics (PRD §2.1): for Caretaker, X-User-ID is a Caretaker.id;
for FosterVolunteer, a FosterHome.id; for the other three roles it is opaque.
"""

import functools

from flask import request

from errors import ApiError, ERR_FORBIDDEN, ERR_UNAUTHENTICATED

ROLES = {
    "ProgramCoordinator",
    "Caretaker",
    "ClinicStaff",
    "AnimalControlOfficer",
    "FosterVolunteer",
}


def authenticate():
    """Validate the identity headers; return (user_id, role)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise ApiError(ERR_UNAUTHENTICATED, 401,
                       "Missing or unknown X-User-Role / X-User-ID headers.")
    return user_id, role


def require_roles(*allowed_roles):
    """Decorator: authenticate, then authorize against the endpoint's roles."""
    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            user_id, role = authenticate()
            if role not in allowed_roles:
                raise ApiError(
                    ERR_FORBIDDEN, 403,
                    f"Role {role} is not permitted on this endpoint.")
            return fn(*args, user_id=user_id, role=role, **kwargs)
        return wrapper
    return decorator


def json_body():
    """Parse the request JSON body; absent or non-JSON bodies become {}."""
    return request.get_json(force=True, silent=True) or {}
