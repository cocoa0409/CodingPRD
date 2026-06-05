"""Auth header extraction and RBAC enforcement.

Auth headers (PRD §2.1): X-User-ID and X-User-Role.
Roles: Borrower, Investor, Underwriter, ComplianceOfficer, PlatformAdmin.
"""
from flask import request

import errors

ROLES = {"Borrower", "Investor", "Underwriter", "ComplianceOfficer", "PlatformAdmin"}


def get_identity():
    """Return (user_id, role) from request headers, or (None, None) if absent."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    return user_id, role


def require_auth(allowed_roles, anonymous_ok=False):
    """Validate auth headers and role membership.

    Precedence (PRD §2.7):
      1. ERR_UNAUTHENTICATED (401) if either header missing.
      2. ERR_FORBIDDEN_ROLE (403) if role not permitted.

    anonymous_ok=True means the endpoint allows an unauthenticated caller
    (used for borrower / investor self-registration). When headers ARE present
    on such an endpoint, the role still has to be allowed.

    Returns (user_id, role).
    """
    user_id, role = get_identity()

    if not user_id or not role:
        if anonymous_ok:
            return user_id, role
        raise errors.unauthenticated()

    if role not in allowed_roles:
        raise errors.forbidden_role()

    return user_id, role
