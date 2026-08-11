"""Auth header extraction, role gating, AccountManager ownership (PRD §2.1)."""

from flask import request

from errors import ApiError, ERR_UNAUTHENTICATED, ERR_UNAUTHORIZED

ROLES = {
    "PlatformAdmin",
    "ComplianceOfficer",
    "AccountManager",
    "IntakeOperator",
    "DestructionTechnician",
    "LogisticsCoordinator",
}


def auth_context():
    """Priority 1: both headers present and role is a declared role."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not isinstance(uid, str):
        raise ApiError(ERR_UNAUTHENTICATED, 401, "missing X-User-ID header")
    if not role or role not in ROLES:
        raise ApiError(ERR_UNAUTHENTICATED, 401, "missing or invalid X-User-Role header")
    return uid, role


def require_roles(*allowed):
    """Priority 2: role must be listed for the endpoint."""
    uid, role = auth_context()
    if role not in allowed:
        raise ApiError(ERR_UNAUTHORIZED, 403, f"role {role} is not permitted on this endpoint")
    return uid, role


def check_owns_account(uid, role, account_id):
    """Priority 4: AccountManager may touch only its own account subtree."""
    if role == "AccountManager" and account_id != uid:
        raise ApiError(ERR_UNAUTHORIZED, 403, "AccountManager may only access its own account")
