"""Auth header extraction and RBAC (PRD §2.1, §2.9).

Auth headers (PRD §2.1): X-User-ID (acting principal) and X-User-Role (the
capacity in which they act). Both mandatory; missing/invalid -> 401
ERR_MISSING_AUTH_CONTEXT. The system recognises exactly four roles, spelled
precisely as PlanAdmin, Member, ClinicStaff, BillingAdmin.

Validation order (PRD §2.9): auth presence/validity -> role permission ->
ownership -> existence -> ... .
"""
from flask import request

from errors import err, ERR_MISSING_AUTH_CONTEXT, ERR_FORBIDDEN_ROLE

KNOWN_ROLES = {"PlanAdmin", "Member", "ClinicStaff", "BillingAdmin"}


def authenticate():
    """Validate the two mandatory headers. Returns (user_id, role).

    Raises ERR_MISSING_AUTH_CONTEXT (401) if either header is missing or the
    role is not one of the four recognised roles.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in KNOWN_ROLES:
        raise err(ERR_MISSING_AUTH_CONTEXT, "Missing or invalid auth context")
    return user_id, role


def require_role(role, allowed_roles):
    """Raise ERR_FORBIDDEN_ROLE (403) if role not permitted for the op."""
    if role not in allowed_roles:
        raise err(ERR_FORBIDDEN_ROLE, "Role not permitted for this operation")
