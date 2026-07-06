"""Auth header extraction and RBAC checking."""
from flask import request

from errors import err

ROLES = {"Clerk", "ProbateJudge", "PersonalRepresentative"}


def authenticate():
    """Return (user_id, role) or raise ERR_UNAUTHENTICATED."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise err("ERR_UNAUTHENTICATED", "Missing or invalid authentication headers")
    return user_id, role


def authorize(role, allowed_roles):
    if role not in allowed_roles:
        raise err("ERR_UNAUTHORIZED", "Role not permitted for this operation")
