"""Auth extraction + RBAC (PRD §2.1, SCAFFOLD §1.4 priority 1/2, §1.7).

Headers (verbatim from PRD §2.1):
  X-User-ID    — opaque operator identifier (required)
  X-User-Role  — one of the five recognized roles (required)
"""
from flask import request

from errors import err

ROLES = {
    "PlatformAdmin",
    "VaultController",
    "FieldTech",
    "SettlementOfficer",
    "ComplianceOfficer",
}


def authenticate():
    """Priority 1 — both headers present and the role recognized.

    Returns (user_id, role). Raises ERR_UNAUTHENTICATED (401) otherwise.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise err("ERR_UNAUTHENTICATED", "Missing or invalid authentication headers.")
    return user_id, role


def authorize(role, allowed_roles):
    """Priority 2 — acting role permitted for the operation."""
    if role not in allowed_roles:
        raise err("ERR_FORBIDDEN_ROLE", "Role %s is not permitted for this operation." % role)
