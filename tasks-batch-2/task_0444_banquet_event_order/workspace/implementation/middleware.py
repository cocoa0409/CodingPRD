"""Auth header extraction and RBAC (PRD §2.1, §2.8, §1.7).

Every request must carry X-User-ID and X-User-Role. X-User-Role must name one
of the four known roles. Authorization is decided purely by role.
"""
from flask import request

import errors

KNOWN_ROLES = {"PlatformAdmin", "SalesManager", "BanquetCaptain", "AccountingClerk"}


def authenticate():
    """Return the acting role string, or raise ERR_UNAUTHENTICATED.

    Priority 1 (PRD §2.8): missing X-User-ID or missing/unknown X-User-Role.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in KNOWN_ROLES:
        raise errors.unauthenticated()
    return role


def require_role(role, allowed):
    """Priority 2 (PRD §2.8): role must be in the allowed set for this op."""
    if role not in allowed:
        raise errors.forbidden()
