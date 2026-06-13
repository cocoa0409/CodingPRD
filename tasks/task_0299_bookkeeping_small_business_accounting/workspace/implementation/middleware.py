"""Auth header extraction and RBAC enforcement.

Auth headers (PRD §2.1): X-User-ID and X-User-Role.
Roles (PRD §2.1): Owner, Accountant, Bookkeeper, Auditor.

Validation priority (PRD §3.11 / SCAFFOLD §1.4):
  priority 1: headers present and X-User-Role is a known role -> else
              ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER (400)
  priority 2: role permitted for the endpoint -> else ERR_FORBIDDEN_FOR_ROLE (403)
"""
from flask import request

import errors

ROLES = {"Owner", "Accountant", "Bookkeeper", "Auditor"}


def get_user_context():
    """Return (user_id, role) after validating auth headers. Raises ApiError."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise errors.ApiError(
            errors.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            400,
            "Missing or invalid X-User-ID / X-User-Role header",
        )
    return user_id, role


def require_role(role, allowed):
    """allowed is an iterable of role names permitted for the endpoint."""
    if role not in allowed:
        raise errors.ApiError(
            errors.ERR_FORBIDDEN_FOR_ROLE,
            403,
            "Role %s is not permitted for this operation" % role,
        )
