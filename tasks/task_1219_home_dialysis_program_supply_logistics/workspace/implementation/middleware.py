"""Auth header extraction and role checking (PRD §2.1, pipeline stages 1-3)."""
from functools import wraps

from flask import request

import errors

ALL_ROLES = ["ProgramAdmin", "HomeNurse", "Nephrologist",
             "SupplyCoordinator", "BiomedTechnician", "Patient"]


def get_context():
    """Return (user_id, role) or raise ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER."""
    user_id = request.headers.get("X-User-ID", "").strip()
    role = request.headers.get("X-User-Role", "").strip()
    if not user_id or not role:
        raise errors.err_missing_headers()
    return user_id, role


def require_roles(*roles):
    """Decorator: pipeline stage 1 (headers) then stage 2 (role admission).

    Handler receives (user_id, role) as first two kwargs.
    """
    allowed = set(roles)

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_id, role = get_context()
            if role not in allowed:
                raise errors.err_insufficient_permissions()
            return fn(*args, _user_id=user_id, _role=role, **kwargs)

        return wrapper

    return decorator


def check_patient_ownership(user_id, role, patient_id):
    """Pipeline stage 3: Patient-role caller may only act on own records."""
    if role == "Patient" and user_id != patient_id:
        raise errors.err_forbidden_ownership()
