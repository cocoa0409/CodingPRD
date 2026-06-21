"""Auth header extraction and role checking.

PRD §2.1: every request carries X-User-ID and X-User-Role. Missing/malformed
either -> ERR_MISSING_USER_CONTEXT (401). Role not permitted, or ownership
check fails -> ERR_FORBIDDEN_ROLE (403).

The four roles, spelled precisely (PRD §2.1):
  PlatformAdmin, StoreOps, Customer, Picker.
"""
from flask import request

from errors import err, ERR_MISSING_USER_CONTEXT, ERR_FORBIDDEN_ROLE

VALID_ROLES = {"PlatformAdmin", "StoreOps", "Customer", "Picker"}


def get_user_context():
    """Return (user_id, role) after validating both headers are present and
    well-formed. PRD §2.10 priority (1): this runs before everything else."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or role is None:
        err(ERR_MISSING_USER_CONTEXT, "X-User-ID and X-User-Role headers are required")
    user_id = user_id.strip()
    role = role.strip()
    if not user_id or not role:
        err(ERR_MISSING_USER_CONTEXT, "X-User-ID and X-User-Role headers must be non-empty")
    if role not in VALID_ROLES:
        err(ERR_MISSING_USER_CONTEXT, "X-User-Role is not a recognized role")
    return user_id, role


def require_role(role, allowed):
    """PRD §2.10 priority (2): the declared role must be in the allowed set
    for the operation, else ERR_FORBIDDEN_ROLE."""
    if role not in allowed:
        err(ERR_FORBIDDEN_ROLE, "Role %s is not permitted for this operation" % role)
