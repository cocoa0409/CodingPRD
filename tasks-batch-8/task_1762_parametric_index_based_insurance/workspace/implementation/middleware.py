"""Auth middleware (PRD §2.1, SCAFFOLD §1.4 priorities 1-2).

X-User-ID and X-User-Role headers must both be present; role must be one of the
eight declared roles. Failures -> ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER (400).
Role authorization per endpoint -> ERR_INSUFFICIENT_PERMISSIONS (403).
"""

from flask import request

from errors import (
    err,
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
    ERR_INSUFFICIENT_PERMISSIONS,
)

ROLES = {
    "ProgramManager",
    "Actuary",
    "Underwriter",
    "ClaimsAdjuster",
    "TreasuryOfficer",
    "FraudAnalyst",
    "DataOperations",
    "ServicingAgent",
}

# All eight roles — used for "Any" (all GET) endpoints
ALL_ROLES = frozenset(ROLES)


def get_auth():
    """Validate X-User-ID / X-User-Role; return (user_id, role) or raise."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise err(
            ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            400,
            "X-User-ID or X-User-Role header missing/invalid",
        )
    return user_id, role


def require_roles(*allowed):
    """Return (user_id, role) after auth + role authorization."""
    user_id, role = get_auth()
    if role not in allowed:
        raise err(
            ERR_INSUFFICIENT_PERMISSIONS,
            403,
            "Role not permitted for this endpoint",
        )
    return user_id, role
