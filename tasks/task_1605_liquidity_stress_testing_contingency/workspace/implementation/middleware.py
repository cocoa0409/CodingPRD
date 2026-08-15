"""Auth middleware: X-User-ID / X-User-Role headers and RBAC role checks."""
from functools import wraps

from flask import g, request

from errors import ApiError, ERR_FORBIDDEN, ERR_UNAUTHENTICATED

ALL_ROLES = {
    "TreasuryAnalyst",
    "RiskOfficer",
    "TreasuryOps",
    "LiquidityCommittee",
    "PlatformAdmin",
}

# Shared read access per the RBAC matrix ("all GET endpoints").
BIZ4 = ("TreasuryAnalyst", "RiskOfficer", "TreasuryOps", "LiquidityCommittee")


def require_roles(*roles):
    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_id = request.headers.get("X-User-ID")
            role = request.headers.get("X-User-Role")
            if not user_id or not role or role not in ALL_ROLES:
                raise ApiError(
                    ERR_UNAUTHENTICATED, 401,
                    "Missing X-User-ID / X-User-Role headers or undeclared role.")
            if role not in roles:
                raise ApiError(
                    ERR_FORBIDDEN, 403,
                    f"Role {role} is not permitted for this operation.")
            g.user_id = user_id
            g.role = role
            return fn(*args, **kwargs)
        return wrapper
    return deco
