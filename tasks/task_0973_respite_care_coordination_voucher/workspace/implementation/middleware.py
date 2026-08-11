"""Auth header extraction and role checking per PRD §2.1."""
from flask import request

from errors import err_unauthenticated, err_unauthorized_role, err_forbidden_ownership

ROLES = {"Anonymous", "Caregiver", "Provider", "Coordinator", "FunderAdmin"}


def get_actor():
    """Return (user_id, role) after validating auth headers. Priority 1."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise err_unauthenticated()
    return user_id, role


def require_roles(*allowed):
    """Validate auth then role authorization. Returns (user_id, role)."""
    user_id, role = get_actor()
    if role not in allowed:
        raise err_unauthorized_role()
    return user_id, role


def check_caregiver_ownership(user_id, role, owner_caregiver_id):
    """Priority 3 ownership check for entity-backed Caregiver role."""
    if role == "Caregiver" and user_id != owner_caregiver_id:
        raise err_forbidden_ownership()


def check_provider_ownership(user_id, role, owner_provider_id):
    if role == "Provider" and user_id != owner_provider_id:
        raise err_forbidden_ownership()
