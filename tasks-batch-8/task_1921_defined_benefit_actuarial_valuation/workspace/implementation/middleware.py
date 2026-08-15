"""Auth header extraction and role checking."""

from flask import request
from errors import unauthenticated, unauthorized

ROLES = {"FirmAdmin", "PlanAdmin", "Actuary", "SeniorActuary", "Auditor"}


def authenticate():
    """Validate X-User-Role and X-User-ID headers; return (role, user_id)."""
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if not role or not user_id or role not in ROLES:
        raise unauthenticated()
    return role, user_id


def require_roles(allowed):
    role, user_id = authenticate()
    if role not in allowed:
        raise unauthorized()
    return role, user_id
