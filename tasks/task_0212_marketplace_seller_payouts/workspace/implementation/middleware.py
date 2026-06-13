"""Auth header extraction + role checking (PRD §2.1, §2.11).

Headers (verbatim from PRD §2.1):
  X-User-ID   — caller id (for Seller, this is the acting Seller's id)
  X-User-Role — one of: Seller, PlatformReviewer, PlatformFinance
"""
from flask import request

from errors import err, ERR_UNAUTHENTICATED, ERR_UNAUTHORIZED

ROLE_SELLER = "Seller"
ROLE_REVIEWER = "PlatformReviewer"
ROLE_FINANCE = "PlatformFinance"
VALID_ROLES = {ROLE_SELLER, ROLE_REVIEWER, ROLE_FINANCE}


def get_identity():
    """Return (user_id, role). Raises ERR_UNAUTHENTICATED if either header is
    missing/empty, or if the role is not one of the three valid roles."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role:
        raise err(ERR_UNAUTHENTICATED, "Missing X-User-ID or X-User-Role header.")
    if role not in VALID_ROLES:
        raise err(ERR_UNAUTHENTICATED, "Unknown role.")
    return user_id, role


def require_roles(role, allowed):
    """Authorization gate (ERR_UNAUTHORIZED). `allowed` is an iterable of role
    names permitted for the operation."""
    if role not in allowed:
        raise err(ERR_UNAUTHORIZED, "Role not permitted for this operation.")
