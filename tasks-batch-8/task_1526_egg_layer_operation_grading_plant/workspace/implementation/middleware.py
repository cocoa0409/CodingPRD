"""Auth header extraction and role checking (PRD §2.1, tiers 1-2)."""
from functools import wraps

from flask import request

from errors import ApiError, ERR_UNAUTHENTICATED, ERR_FORBIDDEN

ROLES = {
    "PlatformAdmin",
    "FarmManager",
    "QualityGrader",
    "QAManager",
    "ContractManager",
    "ComplianceOfficer",
}
ALL_ROLES = sorted(ROLES)


def authenticate():
    """Tier 1: X-User-ID and X-User-Role present and role declared -> else 401."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise ApiError(ERR_UNAUTHENTICATED, 401, "Missing or unknown X-User-Role / X-User-ID headers")
    return uid, role


def endpoint(roles):
    """Decorator: tier 1 auth then tier 2 RBAC. Injects actor=<X-User-ID>."""
    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            uid, role = authenticate()
            if role not in roles:
                raise ApiError(ERR_FORBIDDEN, 403, "Role not permitted on this endpoint")
            kwargs["actor"] = uid
            return fn(*args, **kwargs)
        return wrapper
    return deco
