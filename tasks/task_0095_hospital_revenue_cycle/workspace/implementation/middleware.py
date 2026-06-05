"""Auth header extraction and role checking (PRD 2.1, 2.7)."""
from flask import request

import errors

VALID_ROLES = {"Registrar", "Coder", "BillingSpecialist", "FinanceManager"}


def authenticate():
    """Validate X-User-ID and X-User-Role headers. Returns (user_id, role).

    A request missing either header, or carrying a malformed value, is rejected
    with ERR_UNAUTHENTICATED (401). 'Malformed role' includes any value not in
    the set of exactly four roles.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or role is None:
        raise errors.unauthenticated()
    if not isinstance(user_id, str) or user_id.strip() == "":
        raise errors.unauthenticated()
    if not isinstance(role, str) or role.strip() == "":
        raise errors.unauthenticated()
    if role not in VALID_ROLES:
        raise errors.unauthenticated()
    return user_id, role


def require_role(role, allowed):
    """Enforce RBAC: ERR_FORBIDDEN_ROLE (403) if role not in allowed set."""
    if role not in allowed:
        raise errors.forbidden_role()
