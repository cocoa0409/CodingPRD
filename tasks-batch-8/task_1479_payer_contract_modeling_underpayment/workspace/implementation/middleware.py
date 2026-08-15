"""Auth header extraction and role checking (PRD §2.1, §2.8 rungs 1-2)."""

from flask import request

from errors import err_missing_user_context, err_forbidden

ROLES = {
    "ContractAnalyst",
    "ContractManager",
    "RevenueIntegrityAnalyst",
    "RecoveryManager",
    "FinanceDirector",
    "SystemAdmin",
    "Auditor",
}

ALL_ROLES = sorted(ROLES)


def get_user_context():
    """Returns (user_id, role). Raises ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise err_missing_user_context()
    return user_id, role


def require_roles(allowed):
    """Returns (user_id, role) after enforcing rung 1 + rung 2."""
    user_id, role = get_user_context()
    if role not in allowed:
        raise err_forbidden()
    return user_id, role
