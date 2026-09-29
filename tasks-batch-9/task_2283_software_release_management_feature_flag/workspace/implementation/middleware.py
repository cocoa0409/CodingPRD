"""Authentication and RBAC (PRD 2.1, rejection ladder ranks 1-2)."""

from flask import request

from errors import fail

ROLES = (
    "PlatformAdmin",
    "ReleaseManager",
    "Engineer",
    "ChangeApprover",
    "ComplianceOfficer",
    "SRE",
)

ANY = tuple(ROLES)


def authenticate(allowed_roles):
    """Rank 1 then rank 2.  Returns (user_id, role)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or not str(user_id).strip():
        fail("ERR_UNAUTHENTICATED", "X-User-ID header is required")
    if role is None or not str(role).strip():
        fail("ERR_UNAUTHENTICATED", "X-User-Role header is required")
    if role not in ROLES:
        fail("ERR_UNAUTHENTICATED", "Unknown role '%s'" % role)
    if role not in allowed_roles:
        fail("ERR_ROLE_NOT_PERMITTED", "Role %s may not perform this operation" % role)
    return user_id, role
