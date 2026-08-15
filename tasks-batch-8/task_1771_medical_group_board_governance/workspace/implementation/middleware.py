"""Auth header extraction and role checking (scaffold §1.4 priority 1/3/4, §1.7)."""
from flask import request

from errors import raise_err, ERR_UNAUTHENTICATED, ERR_FORBIDDEN, ERR_RESOURCE_OWNERSHIP

ROLES = ("BoardAdmin", "Physician", "ComplianceOfficer")


def get_auth():
    """Extract and validate X-User-Role / X-User-ID headers.

    Returns (role, user_id). Raises ERR_UNAUTHENTICATED when role header is
    missing/unrecognized, or X-User-ID is missing for the entity-backed
    Physician role.
    """
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if role is None or role not in ROLES:
        raise_err(ERR_UNAUTHENTICATED, "Missing or invalid X-User-Role")
    if role == "Physician" and not user_id:
        raise_err(ERR_UNAUTHENTICATED, "X-User-ID required for Physician role")
    # For opaque roles X-User-ID is optional; keep whatever was sent.
    return role, user_id


def require_roles(role, allowed):
    if role not in allowed:
        raise_err(ERR_FORBIDDEN, "Role not permitted on this endpoint")


def check_ownership(role, user_id, owner_physician_id):
    """Physician callers may only act on their own resources."""
    if role == "Physician" and user_id != owner_physician_id:
        raise_err(ERR_RESOURCE_OWNERSHIP, "Physician may only act on own resources")
