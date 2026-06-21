"""Auth header extraction and role enforcement (PRD §2.1).

Two mandatory headers:
  X-User-ID    : opaque operator identifier (never compared to entity ids)
  X-User-Role  : one of HerdManager, Veterinarian, SaleClerk, FeedlotOperator, Auditor

Missing/malformed header -> ERR_UNAUTHENTICATED (401).
Authenticated but role not permitted for the endpoint -> ERR_FORBIDDEN (403).
"""
from flask import request

import errors

ROLES = {"HerdManager", "Veterinarian", "SaleClerk", "FeedlotOperator", "Auditor"}


def authenticate():
    """Validate the two auth headers. Returns the acting role.

    Raises ERR_UNAUTHENTICATED when either header is missing/blank or the role
    value is not one of the five recognized roles.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or role is None:
        raise errors.unauthenticated()
    if not str(user_id).strip() or not str(role).strip():
        raise errors.unauthenticated()
    if role not in ROLES:
        raise errors.unauthenticated()
    return role


def require_role(role, allowed):
    """Raise ERR_FORBIDDEN unless `role` is in the allowed set."""
    if role not in allowed:
        raise errors.forbidden()
