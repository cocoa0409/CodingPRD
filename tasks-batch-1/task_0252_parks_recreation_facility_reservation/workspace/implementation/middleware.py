"""Auth header extraction and role checking (PRD §2.1).

Every request carries X-User-ID and X-User-Role. Valid roles: RecCoordinator,
Patron, FinanceClerk. Missing/unknown role -> ERR_UNAUTHENTICATED (401).
Role not permitted for the operation -> ERR_FORBIDDEN (403).
"""
from flask import request

import errors

VALID_ROLES = {"RecCoordinator", "Patron", "FinanceClerk"}


def get_identity():
    """Return (user_id, role). Raises ERR_UNAUTHENTICATED if role invalid."""
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if role is None or role not in VALID_ROLES:
        raise errors.err(errors.ERR_UNAUTHENTICATED, "Missing or unknown X-User-Role header")
    return user_id, role


def require_roles(role, allowed):
    """Raise ERR_FORBIDDEN if `role` is not in `allowed`."""
    if role not in allowed:
        raise errors.err(errors.ERR_FORBIDDEN, "Acting role not permitted for this operation")
