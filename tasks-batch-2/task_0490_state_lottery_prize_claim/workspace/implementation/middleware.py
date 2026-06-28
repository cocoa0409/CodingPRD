"""Auth header extraction and RBAC enforcement (PRD 2.1, scaffold 1.7)."""
from flask import request

from errors import err

VALID_ROLES = {"LicensingAdmin", "TerminalOperator", "ClaimsClerk", "LotteryOfficer"}


def get_auth():
    """Return (user_id, role). Raise ERR_UNAUTHENTICATED if missing/malformed."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not isinstance(user_id, str) or not user_id.strip():
        raise err("ERR_UNAUTHENTICATED", "Missing or malformed X-User-ID header")
    if not role or role not in VALID_ROLES:
        raise err("ERR_UNAUTHENTICATED", "Missing or malformed X-User-Role header")
    return user_id, role


def require_roles(role, allowed):
    if role not in allowed:
        raise err("ERR_FORBIDDEN", f"Role {role} may not perform this operation")
