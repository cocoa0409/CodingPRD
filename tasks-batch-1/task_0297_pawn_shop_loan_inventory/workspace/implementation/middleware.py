"""Auth header extraction and RBAC enforcement (PRD §2.1, §2.11).

Headers: X-User-ID and X-User-Role. Roles spelled exactly:
Appraiser, LoanOfficer, ShopManager, Customer, LawEnforcement.
"""
from flask import request

from errors import err

ROLES = {"Appraiser", "LoanOfficer", "ShopManager", "Customer", "LawEnforcement"}


def get_identity():
    """Return (user_id, user_role) from headers, or (None, None) if absent."""
    user_id = request.headers.get("X-User-ID")
    user_role = request.headers.get("X-User-Role")
    return user_id, user_role


def require_auth(allowed_roles):
    """Enforce auth (401) then RBAC (403). Returns (user_id, user_role).

    Priority is pinned by PRD §2.11:
      (1) ERR_UNAUTHENTICATED — missing either header, or X-User-Role not a
          recognized role.
      (2) ERR_FORBIDDEN_ROLE — well-formed headers but role not permitted.
    """
    user_id, user_role = get_identity()
    if not user_id or not user_role or user_role not in ROLES:
        raise err(
            "ERR_UNAUTHENTICATED",
            "Missing or invalid X-User-ID / X-User-Role header.",
        )
    if allowed_roles is not None and user_role not in allowed_roles:
        raise err(
            "ERR_FORBIDDEN_ROLE",
            "Role {} is not permitted for this operation.".format(user_role),
        )
    return user_id, user_role
