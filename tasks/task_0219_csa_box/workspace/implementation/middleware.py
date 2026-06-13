"""Auth header extraction and RBAC enforcement.

Auth headers (PRD §2.1 / SCAFFOLD §1.4 priority 1):
  - X-User-ID   : identifies the acting principal
  - X-User-Role : one of FarmManager, DeliveryCoordinator, Member,
                  PlatformAdmin, Anonymous
Missing/malformed -> ERR_UNAUTHENTICATED (401).
Role not permitted -> ERR_FORBIDDEN_ROLE (403).
"""
from flask import request

from errors import err, ERR_UNAUTHENTICATED, ERR_FORBIDDEN_ROLE

VALID_ROLES = {"FarmManager", "DeliveryCoordinator", "Member",
               "PlatformAdmin", "Anonymous"}


def get_auth():
    """Return (user_id, role) from the request headers, or None values."""
    return request.headers.get("X-User-ID"), request.headers.get("X-User-Role")


def require_auth():
    """Validate presence + well-formedness of auth headers (priority 1).

    Returns (user_id, role). Raises ERR_UNAUTHENTICATED if either header is
    missing/blank or the role is not a recognized value."""
    user_id, role = get_auth()
    if role is None or role.strip() == "":
        raise err(ERR_UNAUTHENTICATED, "Missing or malformed X-User-Role header.")
    if role not in VALID_ROLES:
        raise err(ERR_UNAUTHENTICATED, "Unrecognized X-User-Role value.")
    # X-User-ID must be present and non-blank for any authenticated role. The
    # Anonymous role legitimately carries no X-User-ID (PRD §2.1); for a
    # protected endpoint it will instead be rejected at role authorization (403).
    if role != "Anonymous" and (user_id is None or user_id.strip() == ""):
        raise err(ERR_UNAUTHENTICATED, "Missing or malformed X-User-ID header.")
    return user_id, role


def require_role(allowed_roles):
    """Enforce auth (priority 1) then role authorization (priority 2).

    Returns (user_id, role)."""
    user_id, role = require_auth()
    if role not in allowed_roles:
        raise err(ERR_FORBIDDEN_ROLE,
                  "Role %s is not permitted for this operation." % role)
    return user_id, role
