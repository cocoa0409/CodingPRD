"""Auth header extraction and RBAC enforcement (PRD §2.1, §1.7)."""
from flask import request

import errors

KNOWN_ROLES = {
    "WeighMaster",
    "PayoutClerk",
    "YardManager",
    "SettlementAccountant",
    "ComplianceOfficer",
}


def authenticate():
    """Validate X-User-ID and X-User-Role headers. Returns (user_id, role).

    Raises ERR_UNAUTHENTICATED (401) when either header is missing/empty or the
    role is not a known role.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in KNOWN_ROLES:
        raise errors.unauthenticated()
    return user_id, role


def require_roles(role, allowed):
    """Raise ERR_FORBIDDEN_ROLE (403) if role not in the allowed set."""
    if role not in allowed:
        raise errors.forbidden_role()
