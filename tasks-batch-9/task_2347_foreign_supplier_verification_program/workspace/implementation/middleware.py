"""Auth header extraction and RBAC (PRD sections 2.1 and 2.11 rungs 1-2)."""
from functools import wraps

from flask import g, request

from errors import fail

ROLES = (
    "ComplianceOfficer",
    "QualifiedIndividual",
    "EntryFiler",
    "FdaInspector",
    "PlatformAdmin",
)

CO = "ComplianceOfficer"
QI = "QualifiedIndividual"
EF = "EntryFiler"
FDA = "FdaInspector"
PA = "PlatformAdmin"


def endpoint(roles):
    """Rung 1 (ERR_UNAUTHENTICATED) then rung 2 (ERR_ROLE_NOT_PERMITTED)."""

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_id = request.headers.get("X-User-ID")
            role = request.headers.get("X-User-Role")
            if not user_id or not role or role not in ROLES:
                fail("ERR_UNAUTHENTICATED")
            if role not in roles:
                fail("ERR_ROLE_NOT_PERMITTED")
            g.user_id = user_id
            g.role = role
            return fn(*args, **kwargs)

        return wrapper

    return decorator
