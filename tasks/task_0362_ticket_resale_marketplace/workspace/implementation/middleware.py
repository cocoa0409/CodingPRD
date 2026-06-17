"""Auth header extraction and role checking (PRD §2.1).

Every request carries X-User-ID and X-User-Role. Roles: PlatformAdmin, Seller,
Buyer, TrustSafety. Seller/Buyer are entity-backed (X-User-ID is the entity id);
PlatformAdmin/TrustSafety are opaque operators.
"""
from flask import request

import errors
from errors import err

VALID_ROLES = {"PlatformAdmin", "Seller", "Buyer", "TrustSafety"}


def get_user_context():
    """Return (user_id, role). Raises ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER
    if either header is missing/blank or the role is not a recognized value."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or role is None:
        raise err(errors.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
                  "X-User-ID and X-User-Role headers are required")
    user_id = user_id.strip()
    role = role.strip()
    if user_id == "" or role == "":
        raise err(errors.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
                  "X-User-ID and X-User-Role headers must be non-empty")
    if role not in VALID_ROLES:
        raise err(errors.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
                  "X-User-Role is not a recognized role")
    return user_id, role


def require_role(role, allowed):
    """Check the acting role is permitted for the operation (ERR_FORBIDDEN_ROLE)."""
    if role not in allowed:
        raise err(errors.ERR_FORBIDDEN_ROLE,
                  "Role %s is not permitted for this operation" % role)


def require_ownership(role, user_id, owner_id):
    """For an entity-backed role, X-User-ID must equal the resource owner id.
    Opaque roles (PlatformAdmin, TrustSafety) are not ownership-scoped."""
    if role in ("PlatformAdmin", "TrustSafety"):
        return
    if user_id != owner_id:
        raise err(errors.ERR_FORBIDDEN_ROLE,
                  "Caller does not own the targeted resource")
