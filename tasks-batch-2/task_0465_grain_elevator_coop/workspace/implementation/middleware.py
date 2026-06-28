"""Auth header extraction and RBAC. Header names and role values come verbatim
from PRD §2.1."""
from flask import request

import errors

KNOWN_ROLES = {"Merchandiser", "GradeClerk", "SettlementOfficer", "ShippingClerk", "RiskManager"}


def get_role():
    """PRD §2.1: every request carries X-User-ID (opaque) and X-User-Role.
    If X-User-Role is missing or not a known role -> ERR_UNAUTHENTICATED (401)."""
    role = request.headers.get("X-User-Role")
    if role is None or role not in KNOWN_ROLES:
        raise errors.unauthenticated()
    return role


def require_roles(allowed_roles):
    """Validate auth (401) then RBAC (403) in PRD §2.6 precedence order."""
    role = get_role()
    if role not in allowed_roles:
        raise errors.forbidden()
    return role
