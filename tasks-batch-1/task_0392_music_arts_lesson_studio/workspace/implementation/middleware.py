"""Auth header extraction and role checking.

PRD §2.1: every request carries X-User-ID and X-User-Role. Missing/malformed ->
ERR_MISSING_USER_CONTEXT (401). Role not permitted -> ERR_INSUFFICIENT_PERMISSIONS (403).
Recognized roles: StudioAdmin, Instructor, ParentGuardian, BillingClerk.
"""
from flask import request

import errors

VALID_ROLES = {"StudioAdmin", "Instructor", "ParentGuardian", "BillingClerk"}


def require_auth():
    """Validate presence/well-formedness of identity headers. Returns (user_id, role)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not isinstance(user_id, str) or not user_id.strip():
        errors.raise_error(errors.ERR_MISSING_USER_CONTEXT,
                           "Missing or malformed X-User-ID header")
    if not role or role not in VALID_ROLES:
        errors.raise_error(errors.ERR_MISSING_USER_CONTEXT,
                           "Missing or malformed X-User-Role header")
    return user_id, role


def require_role(role, allowed):
    """role must be in the allowed set, else 403."""
    if role not in allowed:
        errors.raise_error(errors.ERR_INSUFFICIENT_PERMISSIONS,
                           "Role %s not permitted for this operation" % role)
