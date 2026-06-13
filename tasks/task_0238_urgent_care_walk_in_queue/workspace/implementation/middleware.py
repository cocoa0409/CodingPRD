"""Auth header extraction and RBAC enforcement (PRD §2.1, §2.6, §1.7)."""
from flask import request
from errors import err

VALID_ROLES = {
    "ClinicManager", "FrontDeskClerk", "TriageNurse", "Provider", "Patient", "Anonymous",
}


def get_identity():
    """Return (user_id, user_role). Either may be None if header absent."""
    return request.headers.get("X-User-ID"), request.headers.get("X-User-Role")


def authenticate():
    """Enforce that X-User-ID and X-User-Role are present (PRD §2.1).
    Returns the (user_id, role) tuple. Raises ERR_UNAUTHENTICATED otherwise."""
    user_id, role = get_identity()
    if not user_id or not role:
        raise err("ERR_UNAUTHENTICATED", "Missing X-User-ID or X-User-Role header")
    return user_id, role


def authorize(allowed_roles):
    """Authenticate then check the acting role is in allowed_roles.
    Returns (user_id, role). Raises on failure."""
    user_id, role = authenticate()
    if role not in allowed_roles:
        raise err("ERR_FORBIDDEN_ROLE", "Role not permitted for this operation")
    return user_id, role
