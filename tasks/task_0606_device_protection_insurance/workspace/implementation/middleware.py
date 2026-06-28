"""Auth header extraction and RBAC."""
from flask import request

import errors

VALID_ROLES = {"PlatformAdmin", "Subscriber", "ClaimsAdjuster", "LogisticsAgent"}


def require_auth():
    """Return (user_id, role). Raise ERR_UNAUTHENTICATED if missing/malformed."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not isinstance(user_id, str) or not user_id.strip():
        errors.fail(errors.ERR_UNAUTHENTICATED, "Missing or invalid X-User-ID header")
    if not role or role not in VALID_ROLES:
        errors.fail(errors.ERR_UNAUTHENTICATED, "Missing or invalid X-User-Role header")
    return user_id.strip(), role


def require_role(role, allowed):
    if role not in allowed:
        errors.fail(errors.ERR_FORBIDDEN_ROLE,
                    f"Role {role} is not permitted for this operation")
