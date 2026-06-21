"""Auth header extraction and role checking (PRD 2.1).

Headers: X-User-ID, X-User-Role.
Roles (spelled precisely): PlatformAdmin, TrustOfficer, Tutor, ParentGuardian, Arbiter.
Two roles are entity-backed: Tutor (X-User-ID == Tutor.id) and
ParentGuardian (X-User-ID == ParentAccount.id).
"""
from flask import request

from errors import (
    ApiError,
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
    ERR_UNAUTHORIZED,
    ERR_NOT_RESOURCE_OWNER,
)

ROLES = {"PlatformAdmin", "TrustOfficer", "Tutor", "ParentGuardian", "Arbiter"}


def get_user_context():
    """Validate presence/well-formedness of the two identity headers (priority 1)."""
    user_id = request.headers.get("X-User-ID")
    user_role = request.headers.get("X-User-Role")
    if user_id is None or user_role is None:
        raise ApiError(*ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
                       message="X-User-ID and X-User-Role headers are required")
    user_id = user_id.strip()
    user_role = user_role.strip()
    if user_id == "" or user_role == "":
        raise ApiError(*ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
                       message="X-User-ID and X-User-Role headers must be non-empty")
    if user_role not in ROLES:
        raise ApiError(*ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
                       message="X-User-Role is not a recognised role")
    return user_id, user_role


def require_role(user_role, allowed_roles):
    """Priority 2: acting role must be permitted for this operation."""
    if user_role not in allowed_roles:
        raise ApiError(*ERR_UNAUTHORIZED,
                       message="role is not permitted to invoke this operation")


def require_owner(user_id, user_role, owner_role, owner_id):
    """Priority 3: entity-backed ownership check.

    Only applies when the caller acts in the entity-backed role that owns the
    resource. owner_role is the role that owns this resource type (Tutor or
    ParentGuardian); owner_id is the resource's owner FK.
    """
    if user_role == owner_role and user_id != owner_id:
        raise ApiError(*ERR_NOT_RESOURCE_OWNER,
                       message="caller does not own this resource")
