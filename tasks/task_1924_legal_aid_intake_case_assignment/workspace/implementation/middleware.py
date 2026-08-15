"""Auth header extraction and role checking (PRD section 2.1)."""
from functools import wraps

from flask import g, request

from errors import ERR_UNAUTHENTICATED, ERR_UNAUTHORIZED_ROLE, fail

ALL_ROLES = [
    "IntakeSpecialist",
    "SupervisingAttorney",
    "StaffAttorney",
    "Paralegal",
    "EthicsOfficer",
    "GrantsManager",
    "ProgramDirector",
]

_ROLE_SET = set(ALL_ROLES)


def require_roles(roles):
    """Validate X-User-ID / X-User-Role, then check role membership."""

    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            uid = request.headers.get("X-User-ID")
            role = request.headers.get("X-User-Role")
            if not uid or not isinstance(uid, str) or not role or role not in _ROLE_SET:
                fail(ERR_UNAUTHENTICATED,
                     "Missing or invalid X-User-ID / X-User-Role headers")
            if role not in roles:
                fail(ERR_UNAUTHORIZED_ROLE,
                     "Role {} is not permitted for this endpoint".format(role))
            g.user_id = uid
            g.user_role = role
            return fn(*args, **kwargs)

        return wrapper

    return deco
