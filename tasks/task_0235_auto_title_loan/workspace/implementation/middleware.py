"""Auth header extraction and RBAC (PRD 2.1, scaffold §1.4 validations).

Two mandatory headers: X-User-ID and X-User-Role. Six roles, spelled exactly:
ComplianceAdmin, Appraiser, Underwriter, LoanServicer, RecoveryManager, TitleClerk.
"""
from flask import request

from errors import err

VALID_ROLES = {
    "ComplianceAdmin",
    "Appraiser",
    "Underwriter",
    "LoanServicer",
    "RecoveryManager",
    "TitleClerk",
}


def authenticate():
    """Validate the two mandatory auth headers. Returns (user_id, role).

    Missing or malformed -> ERR_UNAUTHENTICATED (401).
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or role is None:
        raise err("ERR_UNAUTHENTICATED", "missing X-User-ID or X-User-Role header")
    if not isinstance(user_id, str) or user_id.strip() == "":
        raise err("ERR_UNAUTHENTICATED", "malformed X-User-ID header")
    if role not in VALID_ROLES:
        raise err("ERR_UNAUTHENTICATED", "malformed X-User-Role header")
    return user_id, role


def require_role(role, allowed):
    """Enforce RBAC: the acting role must be one of the allowed roles for this op."""
    if role not in allowed:
        raise err("ERR_FORBIDDEN_ROLE", "role %s not permitted for this operation" % role)
