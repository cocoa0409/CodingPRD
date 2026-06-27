"""Auth header extraction and RBAC enforcement.

Auth headers (PRD §2.1):
  X-User-ID    — opaque operator identity (not tied to any persisted entity)
  X-User-Role  — one of Adviser | Staff | Contributor | SalesRep

Validation order (PRD §2.6): auth (401) before authorization (403).
"""
from flask import request

from errors import ApiError, ERR_UNAUTHENTICATED, ERR_FORBIDDEN

VALID_ROLES = {"Adviser", "Staff", "Contributor", "SalesRep"}


def authenticate():
    """Return (user_id, role); raise ERR_UNAUTHENTICATED if either header missing."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role:
        raise ApiError(ERR_UNAUTHENTICATED, 401, "Missing X-User-ID or X-User-Role header")
    return user_id, role


def authorize(role, allowed_roles):
    """Raise ERR_FORBIDDEN unless role is in allowed_roles."""
    if role not in allowed_roles:
        raise ApiError(ERR_FORBIDDEN, 403, "Role '%s' is not permitted for this operation" % role)
