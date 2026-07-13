"""Auth headers, role recognition and RBAC (PRD §2.1, §2.6 steps 1-2)."""
from functools import wraps

from flask import g, request

from errors import ApiError

ROLES = ("Customer", "LabTechnician", "PrivacyOfficer", "PlatformAdmin")


def authenticate():
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED")
    g.user_id = user_id
    g.role = role


def endpoint(roles):
    """Decorator: step 1 (authentication) then step 2 (role authorization)."""

    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            authenticate()
            if g.role not in roles:
                raise ApiError("ERR_FORBIDDEN_ROLE")
            return fn(*args, **kwargs)

        return wrapper

    return deco


def is_customer():
    return g.role == "Customer"


def acting_id():
    return g.user_id


def require_owner(customer_id):
    """Ownership check (PRD §2.6 step 5). Operator roles are opaque and exempt."""
    if is_customer() and customer_id != g.user_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")
