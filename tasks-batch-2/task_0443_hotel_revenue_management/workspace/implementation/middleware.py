"""Auth header extraction and RBAC (PRD §2.1, §2.9).

Auth headers (PRD §2.1): X-User-ID (opaque identity) and X-User-Role
(operational role). Both mandatory. Authorization is decided purely by role.

Validation order (PRD §2.9): auth (ERR_UNAUTHENTICATED) -> RBAC
(ERR_FORBIDDEN) -> existence -> body well-formedness -> FK -> business rules.
"""
from flask import request

from errors import err, ERR_UNAUTHENTICATED, ERR_FORBIDDEN

KNOWN_ROLES = {"RevenueManager", "GroupSalesManager", "ChannelManager", "Analyst"}


def authenticate():
    """Validate the two mandatory headers. Returns (user_id, role).

    Raises ERR_UNAUTHENTICATED if either header is missing or the role is
    unknown.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in KNOWN_ROLES:
        raise err(ERR_UNAUTHENTICATED, "Missing or unknown user context")
    return user_id, role


def require_role(role, allowed_roles):
    """Raise ERR_FORBIDDEN if role not in the allowed set for the operation."""
    if role not in allowed_roles:
        raise err(ERR_FORBIDDEN, "Role not permitted for this operation")
