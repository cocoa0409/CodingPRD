"""Auth header extraction and role checking per PRD §2.1."""
from flask import request
from errors import unauthenticated, forbidden_role

ROLES = {
    "CompAdmin",
    "CompAnalyst",
    "CompManager",
    "HRBP",
    "FinancePartner",
    "DepartmentManager",
}


def get_auth():
    """Return (user_id, role). Raises 401 when headers missing/invalid."""
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if role is None or role not in ROLES:
        raise unauthenticated()
    if user_id is None or user_id == "":
        raise unauthenticated()
    return user_id, role


def require_roles(*allowed):
    """Check auth and role membership. Returns (user_id, role)."""
    user_id, role = get_auth()
    if role not in allowed:
        raise forbidden_role()
    return user_id, role
