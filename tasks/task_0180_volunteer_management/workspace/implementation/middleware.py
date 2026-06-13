"""Auth header extraction + RBAC (PRD §2.1, §2.7).

Every request must carry X-User-ID and X-User-Role. The system recognizes
exactly four roles: Volunteer, ShiftCoordinator, ComplianceOfficer,
CorporateSponsor. A missing/blank/unknown header -> ERR_MISSING_OR_INVALID_USER_
CONTEXT_HEADER (400). Headers valid but role not permitted for the operation ->
ERR_UNAUTHORIZED (403).

Validation order (PRD §2.7): header presence+validity FIRST, then role
permission, then path existence, then body FK existence, then org-archived, then
target state, then business rules.
"""
from functools import wraps
from flask import request, g

from errors import ApiError

VALID_ROLES = {
    "Volunteer",
    "ShiftCoordinator",
    "ComplianceOfficer",
    "CorporateSponsor",
}


def require_auth():
    """Validate the user-context headers. Raises
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER (400) when a header is
    missing/blank or X-User-Role is not one of the four known roles. Stores the
    acting id+role on flask.g."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not isinstance(user_id, str) or user_id.strip() == "":
        raise ApiError("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
                       "X-User-ID header missing or invalid")
    if not role or role not in VALID_ROLES:
        raise ApiError("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
                       "X-User-Role header missing or invalid")
    g.user_id = user_id
    g.role = role
    return user_id, role


def require_role(*allowed_roles):
    """Decorator: authenticate then enforce role membership. The wrapped view
    runs only after both pass, so ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER
    (400) always precedes ERR_UNAUTHORIZED (403) which precedes everything
    else."""
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            require_auth()
            if g.role not in allowed_roles:
                raise ApiError("ERR_UNAUTHORIZED",
                               "Role %s is not permitted for this operation" % g.role)
            return fn(*args, **kwargs)
        return wrapper
    return decorator
