"""Auth middleware: X-User-ID / X-User-Role headers, RBAC per endpoint."""
from functools import wraps

from flask import request

from errors import ApiError, ERR_UNAUTHENTICATED, ERR_FORBIDDEN

ROLES = {"LegalOpsManager", "LegalOpsAnalyst", "LegalOpsExecutive"}


def current_user():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if uid is None or not isinstance(uid, str) or not uid.strip():
        raise ApiError(ERR_UNAUTHENTICATED, 401, "Missing or malformed X-User-ID header")
    if role is None or role not in ROLES:
        raise ApiError(ERR_UNAUTHENTICATED, 401, "Missing or malformed X-User-Role header")
    return uid, role


def require_roles(*allowed):
    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            uid, role = current_user()
            if role not in allowed:
                raise ApiError(ERR_FORBIDDEN, 403, "Role is not authorized for this endpoint")
            return fn(*args, user_id=uid, role=role, **kwargs)
        return wrapper
    return deco
