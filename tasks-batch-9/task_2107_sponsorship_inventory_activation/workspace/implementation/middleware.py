"""Authentication, RBAC and sponsor scoping (PRD 2.1, 2.8 rungs 1-2 and 4)."""

from functools import wraps

from flask import request, g

from errors import ApiError

ROLES = (
    "PropertyAdmin",
    "SponsorshipSeller",
    "ContractApprover",
    "ActivationManager",
    "PerformanceAuditor",
    "SponsorContact",
)


def authenticate():
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", 401)
    g.user_id = user_id
    g.role = role
    return user_id, role


def endpoint(roles):
    """Rung 1 then rung 2: authenticate, then authorize the endpoint role list."""
    allowed = set(roles)

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            user_id, role = authenticate()
            if role not in allowed:
                raise ApiError("ERR_ROLE_NOT_PERMITTED", 403)
            return func(*args, **kwargs)

        return wrapper

    return decorator


def sponsor_scope_guard(contract):
    """Rung 4 — a SponsorContact may only touch its own sponsor's contracts."""
    if g.role == "SponsorContact" and contract["sponsor_id"] != g.user_id:
        raise ApiError("ERR_SPONSOR_SCOPE_VIOLATION", 403)
