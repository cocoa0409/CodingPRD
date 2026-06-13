"""Auth header extraction and RBAC enforcement (PRD section 2.1).

Two mandatory headers on every request:
  - X-User-ID  : acting user identifier
  - X-User-Role: one of VenueManager | Coordinator | Guardian | FinanceClerk

Missing header or unknown role -> ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER (401).
Role not permitted for the operation -> ERR_INSUFFICIENT_PERMISSIONS (403).

Guardian identity is entity-backed: for booking-scoped writes the booking's
guardian_user_id must equal X-User-ID, else ERR_INSUFFICIENT_PERMISSIONS.
"""

from flask import request

from errors import err

KNOWN_ROLES = {"VenueManager", "Coordinator", "Guardian", "FinanceClerk"}


def get_user_context():
    """Return (user_id, role) after validating the mandatory headers.

    Raises ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER (priority 1) when either
    header is missing/empty or the role is not one of the four known roles.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in KNOWN_ROLES:
        raise err("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
                  "Missing or invalid X-User-ID / X-User-Role headers")
    return user_id, role


def require_roles(role, allowed):
    """Priority 2 RBAC check: role must be in the allowed set for this op."""
    if role not in allowed:
        raise err("ERR_INSUFFICIENT_PERMISSIONS",
                  "Role %s is not permitted for this operation" % role)
