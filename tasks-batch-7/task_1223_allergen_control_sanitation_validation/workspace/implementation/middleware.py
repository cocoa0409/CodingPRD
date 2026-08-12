from functools import wraps

from flask import g, request

from errors import ApiError

ALL_ROLES = ("QaManager", "QaSupervisor", "QaTechnician", "LineOperator", "Auditor")


def require_roles(*roles):
    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            uid = request.headers.get("X-User-ID")
            role = request.headers.get("X-User-Role")
            if not uid or not isinstance(uid, str) or not role or role not in ALL_ROLES:
                raise ApiError(
                    "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER", 400,
                    "Missing or malformed X-User-ID / X-User-Role headers")
            if role not in roles:
                raise ApiError(
                    "ERR_UNAUTHORIZED_ROLE", 403,
                    f"Role {role} is not permitted on this endpoint")
            g.user_id = uid
            g.user_role = role
            return fn(*args, **kwargs)
        return wrapper
    return deco
