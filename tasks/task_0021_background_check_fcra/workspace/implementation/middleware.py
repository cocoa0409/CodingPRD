"""Auth header extraction and role enforcement.

Per scaffold §1.4 priority order:
  10: ERR_MISSING_AUTH  — X-User-ID and X-User-Role both required
  20: ERR_INVALID_ROLE  — value must be one of the five declared roles
  30: ERR_UNAUTHORIZED  — role present but not permitted for this endpoint
"""

from functools import wraps
from flask import request

from errors import raise_api


VALID_ROLES = {
    "PlatformAdmin",
    "Applicant",
    "Recruiter",
    "ComplianceOfficer",
    "VerificationProvider",
}


def _extract_auth():
    role = request.headers.get("X-User-Role", "").strip()
    user_id = request.headers.get("X-User-ID", "").strip()
    if not user_id or not role:
        raise_api("ERR_MISSING_AUTH", "X-User-ID and X-User-Role required")
    if role not in VALID_ROLES:
        raise_api("ERR_INVALID_ROLE", f"Unknown role: {role}")
    return user_id, role


def require_roles(*allowed_roles):
    allowed_set = set(allowed_roles)

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_id, role = _extract_auth()
            if role not in allowed_set:
                raise_api("ERR_UNAUTHORIZED", f"Role {role} not permitted")
            return fn(*args, _user_id=user_id, _role=role, **kwargs)
        return wrapper
    return decorator


def auth_only(fn):
    """Validate auth headers but do not gate on role."""
    @wraps(fn)
    def wrapper(*args, **kwargs):
        user_id, role = _extract_auth()
        return fn(*args, _user_id=user_id, _role=role, **kwargs)
    return wrapper
