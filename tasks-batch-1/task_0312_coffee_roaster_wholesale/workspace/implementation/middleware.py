"""Auth header extraction + RBAC helpers (PRD §2.1, SCAFFOLD §1.4 priority 1-2).

Auth headers (verbatim from PRD §2.1):
    X-User-ID    : acting user id. For WholesaleBuyer this is the acting account id.
    X-User-Role  : one of RoasterStaff | SalesRep | WholesaleBuyer
"""
from flask import request

import errors

KNOWN_ROLES = {"RoasterStaff", "SalesRep", "WholesaleBuyer"}


def get_identity():
    """Return (user_id, role) after validating presence + known role.

    Raises ERR_UNAUTHENTICATED (priority 1) on missing headers or unknown role.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in KNOWN_ROLES:
        raise errors.unauthenticated()
    return user_id, role


def require_role(role, allowed):
    """Priority-2 RBAC gate: the acting role must be in `allowed`."""
    if role not in allowed:
        raise errors.forbidden()
