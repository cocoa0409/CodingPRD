"""Auth header extraction and RBAC (PRD §2.1, §2.10).

Headers (PRD §2.1):
  X-User-ID    : acting user id (Customer.id when role==Customer, else opaque)
  X-User-Role  : one of the five recognized roles

Validation order (PRD §2.10): auth (401) -> role (403) -> [ownership 403] ->
existence (404) -> state (409) -> business rules -> request shape (400).
"""
from flask import request

import errors

ROLES = {"Customer", "CounterClerk", "Butcher", "ShiftManager", "SafetyOfficer"}


def authenticate():
    """Return (user_id, role) or raise ERR_UNAUTHENTICATED."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        errors.fail(errors.ERR_UNAUTHENTICATED,
                    "Missing or unknown authentication headers.")
    return user_id, role


def require_role(role, allowed):
    """ERR_FORBIDDEN_ROLE if the acting role is not in `allowed`."""
    if role not in allowed:
        errors.fail(errors.ERR_FORBIDDEN_ROLE,
                    "Role %s is not permitted for this operation." % role)
