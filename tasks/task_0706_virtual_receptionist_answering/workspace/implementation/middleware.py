"""Auth header extraction and RBAC checks (PRD §2.1, §2.7).

Headers (verbatim from PRD §2.1):
  X-User-ID   : acting user id
  X-User-Role : PlatformAdmin | AccountOwner | Receptionist
"""
from flask import request

import errors

ROLE_ADMIN = "PlatformAdmin"
ROLE_OWNER = "AccountOwner"
ROLE_RECEPTIONIST = "Receptionist"
VALID_ROLES = {ROLE_ADMIN, ROLE_OWNER, ROLE_RECEPTIONIST}


def get_auth():
    """Return (user_id, role). Raise ERR_UNAUTHENTICATED if either header is
    missing (priority 1). An unrecognized role value is not authenticated."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role:
        raise errors.err(errors.ERR_UNAUTHENTICATED, "Missing X-User-ID or X-User-Role header")
    if role not in VALID_ROLES:
        raise errors.err(errors.ERR_UNAUTHENTICATED, "Unrecognized X-User-Role")
    return user_id, role


def require_role(role, allowed):
    """Priority 2: role must be permitted for this operation (ERR_FORBIDDEN_ROLE)."""
    if role not in allowed:
        raise errors.err(errors.ERR_FORBIDDEN_ROLE, "Role not permitted for this operation")
