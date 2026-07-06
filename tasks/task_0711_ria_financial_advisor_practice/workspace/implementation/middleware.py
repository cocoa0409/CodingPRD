"""Auth header extraction & RBAC (PRD §2.1, §2.7 priorities 1-2)."""

from flask import request

from errors import err

ROLES = {"Advisor", "ComplianceOfficer", "BillingAdmin"}


def authenticate():
    """Priority 1 — X-User-ID and X-User-Role present and role recognized."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise err("ERR_UNAUTHENTICATED", "Missing or unknown authentication headers")
    return user_id, role


def authorize(role, allowed_roles):
    """Priority 2 — role permitted for this operation."""
    if role not in allowed_roles:
        raise err("ERR_FORBIDDEN_ROLE", "Role not permitted for this operation")
