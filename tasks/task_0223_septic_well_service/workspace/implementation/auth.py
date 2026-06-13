"""Auth header extraction and RBAC enforcement (PRD §2.1, SCAFFOLD §1.7).

Headers: X-User-ID and X-User-Role. Roles: Dispatcher, FieldTech,
ComplianceOfficer, Customer.
"""
from flask import request

from errors import err

VALID_ROLES = {"Dispatcher", "FieldTech", "ComplianceOfficer", "Customer"}


def current_identity():
    """Return (user_id, role) after validating both headers are present and the
    role is recognized. Raises ERR_UNAUTHENTICATED otherwise."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in VALID_ROLES:
        raise err("ERR_UNAUTHENTICATED", "Missing or invalid authentication headers")
    return user_id, role


def require_roles(role, allowed):
    """Enforce that `role` is among `allowed`; raises ERR_FORBIDDEN otherwise."""
    if role not in allowed:
        raise err("ERR_FORBIDDEN", "Role not permitted for this operation")
