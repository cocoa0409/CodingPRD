"""Authentication and RBAC (PRD §2.1, SCAFFOLD §1.4 priorities 1-2, §1.7)."""
from functools import wraps

from flask import request

from errors import ERR_UNAUTHENTICATED, ERR_UNAUTHORIZED, fail

ROLES = (
    "LoadControlAdmin",
    "LoadController",
    "RampAgent",
    "DangerousGoodsOfficer",
    "Captain",
    "AuditInspector",
)

ANY_ROLE = ROLES


def current_role():
    return request.headers.get("X-User-Role")


def current_user_id():
    return request.headers.get("X-User-ID") or ""


def authorize(*allowed):
    """Priority 1: authentication. Priority 2: authorisation."""
    allowed_set = set(allowed) if allowed else set(ROLES)

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            role = current_role()
            if role is None or role not in ROLES:
                fail(ERR_UNAUTHENTICATED)
            if role not in allowed_set:
                fail(ERR_UNAUTHORIZED)
            return fn(*args, **kwargs)

        return wrapper

    return decorator
