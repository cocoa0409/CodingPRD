"""Auth header extraction and role checking (PRD §2.1).

Every authenticated endpoint must carry X-User-ID and X-User-Role.
Roles spelled exactly: PlatformAdmin, Account, LabTechnician, Veterinarian, Anonymous.
"""
from flask import request

from errors import err, ERR_UNAUTHENTICATED, ERR_FORBIDDEN_ROLE

VALID_ROLES = {"PlatformAdmin", "Account", "LabTechnician", "Veterinarian", "Anonymous"}


def get_identity():
    """Return (user_id, role) from headers, raising ERR_UNAUTHENTICATED if
    either header is missing or malformed."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not isinstance(user_id, str) or user_id.strip() == "":
        raise err(ERR_UNAUTHENTICATED, "Missing or malformed X-User-ID header")
    if not role or role not in VALID_ROLES:
        raise err(ERR_UNAUTHENTICATED, "Missing or malformed X-User-Role header")
    return user_id, role


def require_roles(allowed_roles):
    """Authenticate, then authorise the acting role against allowed_roles.
    Returns (user_id, role). Priority 1 auth then priority 2 role (PRD §2.8)."""
    user_id, role = get_identity()
    if role not in allowed_roles:
        raise err(ERR_FORBIDDEN_ROLE, "Role %s not permitted for this operation" % role)
    return user_id, role
