"""Auth header extraction and role checking."""
from functools import wraps

from flask import request

from errors import err_unauthenticated, err_forbidden


ROLES = {
    "PlantAdmin",
    "SalesRep",
    "ProductionPlanner",
    "CustomerService",
    "ClaimsAdjuster",
    "Customer",
}


def get_auth():
    """Return (user_id, role) or raise 401."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not isinstance(uid, str) or not uid.strip():
        raise err_unauthenticated()
    if not role or not isinstance(role, str) or role not in ROLES:
        raise err_unauthenticated()
    return uid.strip(), role


def require_roles(*allowed):
    """Decorator: enforce auth + role membership."""
    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            uid, role = get_auth()
            if role not in allowed:
                raise err_forbidden()
            return fn(*args, _user_id=uid, _role=role, **kwargs)
        return wrapper
    return deco
