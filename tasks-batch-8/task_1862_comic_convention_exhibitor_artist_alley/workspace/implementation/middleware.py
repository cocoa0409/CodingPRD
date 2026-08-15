"""Auth middleware per PRD §2.1 and scaffold validations priority 1-2."""

from flask import request

from errors import fail

ROLES = {"ShowDirector", "OperationsStaff", "JuryMember", "Exhibitor", "Anonymous"}


def get_auth():
    """Extract and validate X-User-ID / X-User-Role. Returns (user_id, role)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        fail("ERR_UNAUTHENTICATED",
             "Missing/invalid X-User-Role or X-User-ID headers")
    return user_id, role


def require_roles(*roles):
    user_id, role = get_auth()
    if role not in roles:
        fail("ERR_FORBIDDEN_ROLE",
             "Authenticated role is not in the endpoint's role list")
    return user_id, role
