"""Auth header extraction and RBAC checks per PRD §2.1."""

from functools import wraps

from flask import g, request

from errors import (
    ERR_AUTH_INVALID_ROLE,
    ERR_AUTH_MISSING,
    ERR_FORBIDDEN,
    raise_error,
)


VALID_ROLES = {
    "Grower",
    "Inspector",
    "RegulatoryOfficer",
    "LogisticsOperator",
    "Distributor",
    "Consumer",
}


def require_auth() -> None:
    """Validate X-User-ID / X-User-Role per priority 1 and 2 in scaffold §1.4."""
    user_id = request.headers.get("X-User-ID", "")
    role = request.headers.get("X-User-Role", "")
    if user_id is None:
        user_id = ""
    if role is None:
        role = ""
    user_id = user_id.strip()
    role = role.strip()
    if not user_id or not role:
        raise_error(ERR_AUTH_MISSING, "X-User-ID and X-User-Role headers required")
    if role not in VALID_ROLES:
        raise_error(ERR_AUTH_INVALID_ROLE, f"unrecognized role: {role}")
    g.user_id = user_id
    g.user_role = role


def require_roles(*allowed_roles):
    """Decorator: require the caller's role to be in allowed_roles, else ERR_FORBIDDEN."""

    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            role = getattr(g, "user_role", None)
            if role is None:
                raise_error(ERR_AUTH_MISSING, "auth missing")
            if role not in allowed_roles:
                raise_error(ERR_FORBIDDEN, f"role {role} not permitted on this endpoint")
            return fn(*args, **kwargs)

        return wrapper

    return deco
