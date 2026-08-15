"""Auth header extraction and role enforcement (PRD §2.1)."""
import functools

from flask import g, request

import errors

ROLES = {
    "MedicalStaffCoordinator",
    "CredentialsCommitteeChair",
    "MedicalExecutiveCommitteeChair",
    "BoardMember",
    "DepartmentChief",
    "Practitioner",
    "HearingOfficer",
}

ALL_ROLES = sorted(ROLES)


def require_roles(*allowed):
    """Decorator: rung 1 (headers) then rung 2 (role authorization)."""
    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            user_id = request.headers.get("X-User-ID")
            role = request.headers.get("X-User-Role")
            if not user_id or not role or role not in ROLES:
                errors.raise_err(
                    errors.ERR_AUTH,
                    "X-User-ID and X-User-Role headers are required and the role "
                    "must be one of the declared roles",
                )
            if role not in allowed:
                errors.raise_err(
                    errors.ERR_FORBIDDEN,
                    f"Role {role} is not permitted for this operation",
                )
            g.user_id = user_id
            g.user_role = role
            return fn(*args, **kwargs)
        return wrapper
    return decorator
