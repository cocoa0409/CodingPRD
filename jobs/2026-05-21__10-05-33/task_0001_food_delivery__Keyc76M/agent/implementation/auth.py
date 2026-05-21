"""Header validation and role/ownership helpers."""

from flask import request


ROLES = {"Customer", "Restaurant", "Rider", "CustomerService", "PlatformAdmin"}


def headers():
    """Return (user_id, role) or (None, None) when headers are missing/invalid."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or role not in ROLES:
        return None, None
    return user_id, role


def role_in(role, allowed):
    return role in allowed
