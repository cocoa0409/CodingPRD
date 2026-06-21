"""Auth header extraction (PRD §2.1: X-User-ID + X-User-Role)."""
from flask import request

from errors import raise_err, ERR_UNAUTHENTICATED, ERR_UNAUTHORIZED

VALID_ROLES = {"LoanServicer", "Borrower", "CollectionsAgent"}


def get_auth():
    """Return (user_id, role) or raise ERR_UNAUTHENTICATED.

    Both headers must be present and well-formed; role must be one of the three.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role:
        raise_err(ERR_UNAUTHENTICATED, "Missing X-User-ID or X-User-Role header")
    if role not in VALID_ROLES:
        raise_err(ERR_UNAUTHENTICATED, f"Unknown role {role!r}")
    return user_id, role


def require_role(role: str, allowed: list):
    if role not in allowed:
        raise_err(ERR_UNAUTHORIZED, f"Role {role!r} not permitted")
