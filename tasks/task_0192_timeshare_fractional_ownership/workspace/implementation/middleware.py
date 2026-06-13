"""Auth header extraction and role checking.

Auth headers (PRD 2.1): X-User-ID, X-User-Role.
Roles: ResortManager, Owner, ResaleAgent, ComplianceOfficer, System.
"""
from flask import request

import errors

VALID_ROLES = {"ResortManager", "Owner", "ResaleAgent", "ComplianceOfficer", "System"}


def get_user_context():
    """Validate auth headers; raise ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER on failure.

    Returns (user_id, role).
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in VALID_ROLES:
        raise errors.err(
            errors.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            "X-User-ID and X-User-Role headers must be present and a valid role.",
        )
    return user_id, role


def require_role(role, allowed_roles):
    """Priority-2 RBAC: role must be permitted for this endpoint."""
    if role not in allowed_roles:
        raise errors.err(
            errors.ERR_FORBIDDEN_FOR_ROLE,
            "Role %s is not permitted for this operation." % role,
        )
