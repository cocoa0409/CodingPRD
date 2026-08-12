"""Auth header extraction and role checking."""
from flask import request

import errors

ROLES = {
    "IncidentCommander",
    "ForensicLead",
    "PrivacyCounsel",
    "GeneralCounsel",
    "DataAnalyst",
    "AffectedSubjectRole",
    "Auditor",
}


def current_user():
    """Return (user_id, role). Raises ApiError(401) if missing/malformed."""
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if not role or role not in ROLES:
        raise errors.unauthenticated()
    if not user_id or not user_id.strip():
        raise errors.unauthenticated()
    return user_id, role


def require_role(*allowed):
    """Validate auth headers, then RBAC. Returns (user_id, role)."""
    user_id, role = current_user()
    if role not in allowed:
        raise errors.forbidden()
    return user_id, role
