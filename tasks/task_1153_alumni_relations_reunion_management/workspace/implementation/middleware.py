"""Auth header extraction and role checking per PRD §2.1 / SCAFFOLD §1.4."""

from functools import wraps

from flask import request

from errors import err_unauthenticated, err_unauthorized


ALL_ROLES = [
    "AlumniRelationsStaff",
    "AlumniRelationsDirector",
    "ReunionChair",
    "CommitteeVolunteer",
    "AffinityGroupLeader",
    "Alumni",
]

ENTITY_BACKED_ROLES = {"ReunionChair", "CommitteeVolunteer", "AffinityGroupLeader", "Alumni"}
OPAQUE_ROLES = {"AlumniRelationsStaff", "AlumniRelationsDirector"}


def get_auth():
    """Extract and validate X-User-Role / X-User-ID headers.

    Returns (role, user_id). Raises ERR_UNAUTHENTICATED on any failure.
    """
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if not role or role not in ALL_ROLES:
        raise err_unauthenticated("Missing or invalid X-User-Role header")
    if not user_id:
        raise err_unauthenticated("Missing X-User-ID header")
    return role, user_id


def require_roles(*allowed):
    """Decorator: authenticate, then check the role against the allowed list."""
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            role, user_id = get_auth()
            if role not in allowed:
                raise err_unauthorized("Role not permitted for this endpoint")
            return fn(*args, _role=role, _user_id=user_id, **kwargs)
        return wrapper
    return decorator
