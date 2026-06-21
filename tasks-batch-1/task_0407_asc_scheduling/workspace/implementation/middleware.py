"""Auth header extraction and RBAC (PRD §2.1, §2.6)."""
from flask import request

from errors import err

KNOWN_ROLES = {"Scheduler", "PreOpNurse", "ORManager", "BillingAnalyst"}


def get_user_context():
    """Validate X-User-ID and X-User-Role. Returns (user_id, role).

    Priority 1 (PRD §2.6): both headers present and X-User-Role is a known role,
    else ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER (400).
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in KNOWN_ROLES:
        raise err("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
                  "X-User-ID and X-User-Role headers required; role must be known.")
    return user_id, role


def require_role(role, allowed):
    """Priority 2 (PRD §2.6): role must be permitted, else ERR_INSUFFICIENT_PERMISSIONS (403)."""
    if role not in allowed:
        raise err("ERR_INSUFFICIENT_PERMISSIONS",
                  "Role %s is not permitted for this operation." % role)
