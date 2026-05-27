"""Auth header extraction and role enforcement (§1.4 priorities 1-3, §2.1 of PRD)."""

from functools import wraps
from flask import request

from db import db
from errors import raise_api


VALID_ROLES = {"Applicant", "USPTOExaminer", "USPTOAdmin"}


def _extract_auth():
    role = request.headers.get("X-User-Role", "")
    user_id = request.headers.get("X-User-ID", "")
    if isinstance(role, str):
        role = role.strip()
    if isinstance(user_id, str):
        user_id = user_id.strip()

    # Priority 1: X-User-Role present and is one of the declared roles
    if not role or role not in VALID_ROLES:
        raise_api("ERR_UNAUTHENTICATED", "X-User-Role missing or invalid")

    # Priority 2: X-User-ID present (and resolves to an Applicant when role=Applicant)
    if not user_id:
        raise_api("ERR_UNAUTHENTICATED", "X-User-ID missing")

    if role == "Applicant" and user_id not in db.applicants:
        raise_api("ERR_UNAUTHENTICATED", "X-User-ID does not resolve to an Applicant")

    return user_id, role


def require_roles(*allowed_roles):
    """Decorator: validate auth headers, then check role permissions (priority 3)."""
    allowed_set = set(allowed_roles)

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_id, role = _extract_auth()
            if role not in allowed_set:
                raise_api("ERR_FORBIDDEN", f"Role {role} not permitted on this endpoint")
            return fn(*args, _user_id=user_id, _role=role, **kwargs)

        return wrapper

    return decorator


def auth_only(fn):
    """Decorator: validate auth headers only (no role gate)."""

    @wraps(fn)
    def wrapper(*args, **kwargs):
        user_id, role = _extract_auth()
        return fn(*args, _user_id=user_id, _role=role, **kwargs)

    return wrapper
