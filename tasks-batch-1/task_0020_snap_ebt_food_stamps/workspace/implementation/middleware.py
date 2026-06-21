"""Auth header extraction and role enforcement."""

from functools import wraps
from flask import request

from errors import raise_api


VALID_ROLES = {
    "Caseworker", "Applicant", "Cardholder",
    "BenefitIssuer", "FraudInvestigator", "Merchant", "PolicyAdmin",
}


def _extract_auth():
    role = request.headers.get("X-User-Role", "").strip()
    user_id = request.headers.get("X-User-ID", "").strip()
    # Priority 1: X-User-Role present and is one of the declared roles
    if not role or role not in VALID_ROLES:
        raise_api("ERR_UNAUTHENTICATED", "X-User-Role missing or invalid")
    # Priority 2: X-User-ID present
    if not user_id:
        raise_api("ERR_UNAUTHENTICATED", "X-User-ID missing")
    return user_id, role


def require_roles(*allowed_roles):
    """Decorator: validate auth headers and check role permissions.

    The decorator passes user_id/role into the view via request context (kwargs).
    """
    allowed_set = set(allowed_roles)

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_id, role = _extract_auth()
            if role not in allowed_set:
                raise_api("ERR_FORBIDDEN", f"Role {role} not permitted")
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
