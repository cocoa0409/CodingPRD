"""Auth header extraction and RBAC enforcement."""
from flask import request

import errors

KNOWN_ROLES = {
    "Registrar",
    "ClinicalDirector",
    "Nurse",
    "BillingClerk",
    "ComplianceOfficer",
    "Staff",
}


def get_user_context():
    """Validate the X-User-ID / X-User-Role headers (priority 1).

    Returns (user_id, role). Raises ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER
    when either header is absent or the role is not recognized.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in KNOWN_ROLES:
        errors.raise_error(errors.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
                           "Missing or invalid user context headers")
    return user_id, role


def require_roles(role, allowed):
    """RBAC check (priority 2).

    `allowed` is an iterable of role names permitted for the operation.
    The Staff role is granted read access wherever 'Staff' is in `allowed`.
    """
    if role not in allowed:
        errors.raise_error(errors.ERR_INSUFFICIENT_PERMISSIONS,
                           "Role not permitted for this operation")
