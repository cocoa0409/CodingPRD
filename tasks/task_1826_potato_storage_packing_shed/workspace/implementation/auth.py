"""Auth context (X-User-ID / X-User-Role) and role gating (PRD 2.1)."""
from functools import wraps

from flask import g, request

from util import api_err

ROLES = {
    "ShedAdmin",
    "IntakeClerk",
    "StorageManager",
    "QualityAssuranceManager",
    "SalesManager",
    "PackLineSupervisor",
    "SettlementClerk",
    "Grower",
}


def require_auth():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if (
        uid is None
        or not isinstance(uid, str)
        or uid.strip() == ""
        or role is None
        or role not in ROLES
    ):
        api_err(
            "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
            400,
            "X-User-ID and X-User-Role headers must be present and well-formed",
        )
    g.user_id = uid
    g.user_role = role


def roles_allowed(*roles):
    """RBAC gate: role must be in the endpoint's authorized set (else 403)."""

    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            if g.user_role not in roles:
                api_err(
                    "ERR_INSUFFICIENT_PERMISSIONS",
                    403,
                    f"role {g.user_role} is not permitted for this operation",
                )
            return fn(*args, **kwargs)

        return wrapper

    return deco
