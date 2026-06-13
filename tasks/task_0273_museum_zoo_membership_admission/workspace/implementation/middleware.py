"""Auth header extraction + RBAC role checking (PRD §2.1, scaffold §1.7).

Headers (verbatim from PRD §2.1):
  X-User-ID   — acting user / operator / device / admin identity
  X-User-Role — one of: Patron, BoxOffice, GateScanner, MembershipAdmin
"""
from flask import request

from errors import unauthenticated, forbidden

VALID_ROLES = {"Patron", "BoxOffice", "GateScanner", "MembershipAdmin"}


def get_identity():
    """Return (user_id, role). Raises ERR_UNAUTHENTICATED if role missing/unknown.

    The PRD says auth precedes everything: a request from an unknown role is
    rejected before its body or identifiers are examined.
    """
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if role is None or role not in VALID_ROLES:
        raise unauthenticated()
    return user_id, role


def require_role(role, allowed):
    """Raise ERR_FORBIDDEN_ROLE unless `role` is in the allowed set."""
    if role not in allowed:
        raise forbidden()
