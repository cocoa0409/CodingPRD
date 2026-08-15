"""Auth header extraction and role-based access control (PRD section 2.1)."""
import functools

from flask import request

from errors import err, ERR_UNAUTHENTICATED, ERR_UNAUTHORIZED

ROLES = {
    "ADMIN",
    "REGULATORY_AFFAIRS",
    "QA_MANAGER",
    "QUALITY_ANALYST",
    "PRODUCTION_SUPERVISOR",
    "SUPPLY_CHAIN_PLANNER",
    "COMPLAINT_HANDLER",
}


def get_auth():
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or user_id.strip() == "" or role is None or role.strip() == "":
        raise err(ERR_UNAUTHENTICATED, "X-User-ID and X-User-Role headers are required")
    role = role.strip()
    if role not in ROLES:
        raise err(ERR_UNAUTHENTICATED, "X-User-Role value is not a recognized role")
    return user_id.strip(), role


def authorized(*roles):
    """Decorator: enforce authentication then role authorization."""
    allowed = set(roles)

    def deco(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            user_id, role = get_auth()
            if role not in allowed:
                raise err(ERR_UNAUTHORIZED, "Role %s is not authorized for this endpoint" % role)
            return fn(*args, _user_id=user_id, _role=role, **kwargs)

        return wrapper

    return deco
