"""Authentication and role authorisation (PRD 2.1).

Every request carries X-User-ID (the acting user) and X-User-Role (one of the
six declared roles).  Authentication is always evaluated before authorisation,
and both before the request body is inspected (PRD 2.10 bands 1 and 2).
"""
from flask import request

from errors import fail

ROLES = (
    "ProgramAdmin",
    "TrafficEngineer",
    "CrossingSupervisor",
    "CrossingGuard",
    "SchoolLiaison",
    "PublicReporter",
)


def authenticate():
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or role is None:
        fail("ERR_UNAUTHENTICATED", "Both X-User-ID and X-User-Role are required.")
    user_id = user_id.strip()
    role = role.strip()
    if not user_id or not role:
        fail("ERR_UNAUTHENTICATED", "X-User-ID and X-User-Role must be non-empty.")
    if role not in ROLES:
        fail("ERR_UNAUTHENTICATED", "X-User-Role does not name a declared role.")
    return user_id, role


def require(*allowed_roles):
    """Authenticate, then authorise against the endpoint's role list."""
    user_id, role = authenticate()
    if role not in allowed_roles:
        fail("ERR_UNAUTHORIZED", "Role %s is not authorized for this endpoint." % role)
    return user_id, role
