"""Auth header extraction and RBAC per PRD 2.1 and validations priority 1-2.

Every request must carry X-User-ID and X-User-Role. Missing either, or an
unrecognized role, -> ERR_UNAUTHENTICATED (401). Headers well-formed but role
not permitted -> ERR_UNAUTHORIZED (403). For a Parent, X-User-ID is the acting
Family.id and ownership checks compare a resource's owning Family.id to it.
"""
from flask import request

import errors

VALID_ROLES = {"StudioAdmin", "FrontDeskStaff", "Parent"}


def authenticate():
    """Validate the two auth headers (validation priority 1). Returns (user_id, role)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role:
        raise errors.err(errors.ERR_UNAUTHENTICATED, "Missing X-User-ID or X-User-Role header")
    if role not in VALID_ROLES:
        raise errors.err(errors.ERR_UNAUTHENTICATED, "Unrecognized X-User-Role header")
    return user_id, role


def require_roles(role, allowed):
    """Role authorization (validation priority 2). ERR_UNAUTHORIZED when not allowed."""
    if role not in allowed:
        raise errors.err(errors.ERR_UNAUTHORIZED, "Role not permitted for this operation")


def require_owner(role, user_id, owning_family_id):
    """Parent ownership check (validation priority 2).

    For a Parent, X-User-ID must equal the owning Family.id of the target
    resource. StudioAdmin/FrontDeskStaff are opaque operators and bypass the
    ownership check entirely. owning_family_id may be None when the chain could
    not be resolved (caller should have already raised NOT_FOUND in that case).
    """
    if role == "Parent" and user_id != owning_family_id:
        raise errors.err(errors.ERR_UNAUTHORIZED, "Parent may act only on their own family")
