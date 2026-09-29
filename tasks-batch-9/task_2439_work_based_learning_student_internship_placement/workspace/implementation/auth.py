"""Authentication and role authorisation (PRD 2.1, 2.9 steps 1-2)."""

from flask import request

from errors import fail

ROLES = (
    "WblCoordinator",
    "SafetyReviewer",
    "ComplianceOfficer",
    "EmployerSupervisor",
    "Student",
)


def actor():
    """Step 1: both headers present and the role recognised."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or str(user_id).strip() == "":
        fail("ERR_UNAUTHENTICATED", "X-User-ID header is required.")
    if role is None or str(role).strip() == "":
        fail("ERR_UNAUTHENTICATED", "X-User-Role header is required.")
    if role not in ROLES:
        fail("ERR_UNAUTHENTICATED", "Unrecognised role '%s'." % role)
    return user_id, role


def require(*allowed_roles):
    """Steps 1-2: returns (user_id, role) or raises."""
    user_id, role = actor()
    if role not in allowed_roles:
        fail("ERR_UNAUTHORIZED", "Role %s may not call this endpoint." % role)
    return user_id, role
