"""Auth header extraction and RBAC checking (PRD §2.1, §2.10)."""
from flask import request

import errors

# Exactly five recognized roles (PRD §2.1)
ROLES = {"AMCCoordinator", "ComplianceReviewer", "Appraiser", "LenderUser", "PlatformAdmin"}


def authenticate():
    """Priority 1: headers present and X-User-Role a known role.

    Returns (user_id, role) or raises ERR_UNAUTHENTICATED.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise errors.unauthenticated("Missing or invalid authentication headers.")
    return user_id, role


def require_roles(role, allowed):
    """Priority 3: generic authorization. PlatformAdmin always permitted (override)."""
    if role == "PlatformAdmin":
        return
    if role not in allowed:
        raise errors.unauthorized("Role %s is not permitted for this operation." % role)
