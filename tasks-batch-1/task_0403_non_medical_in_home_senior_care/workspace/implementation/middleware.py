"""Auth header extraction + RBAC (PRD §2.1, §2.6, §1.7)."""
from flask import request

import errors
from errors import ApiError

VALID_ROLES = {"AgencyAdmin", "Scheduler", "Caregiver", "BillingClerk"}


def get_auth():
    """Validate the two mandatory auth headers (PRD §2.1).

    Returns (user_id, role). Raises ERR_MISSING_AUTH (401) if either header is
    missing or malformed.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not user_id.strip():
        raise ApiError(errors.ERR_MISSING_AUTH, 401, "Missing or malformed X-User-ID header")
    if not role or role not in VALID_ROLES:
        raise ApiError(errors.ERR_MISSING_AUTH, 401, "Missing or malformed X-User-Role header")
    return user_id.strip(), role


def require_roles(role, allowed):
    """Authorization tier (PRD §2.6 tier 2)."""
    if role not in allowed:
        raise ApiError(
            errors.ERR_FORBIDDEN_ROLE, 403,
            "Role %s is not permitted for this operation" % role,
        )
