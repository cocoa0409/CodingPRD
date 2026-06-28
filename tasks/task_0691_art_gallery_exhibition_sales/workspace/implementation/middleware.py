"""Auth header extraction + RBAC (PRD §2.1, SCAFFOLD §1.7).

Headers: X-User-ID (acting user) and X-User-Role (operational capacity).
Roles: GalleryAdmin, Registrar, SalesAssociate, Artist.
For non-Artist roles X-User-ID is opaque; for Artist it equals an Artist.id
and drives ownership read-scoping.
"""
from flask import request

import errors

VALID_ROLES = {"GalleryAdmin", "Registrar", "SalesAssociate", "Artist"}


def authenticate():
    """Return (user_id, role) or raise ERR_UNAUTHENTICATED."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role:
        raise errors.unauthenticated()
    if role not in VALID_ROLES:
        raise errors.unauthenticated()
    return user_id, role


def require_role(role, allowed):
    """Raise ERR_FORBIDDEN if `role` is not in the allowed set."""
    if role not in allowed:
        raise errors.forbidden()
