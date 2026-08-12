"""Auth middleware: X-User-ID / X-User-Role header checks and role gating."""

from functools import wraps

from flask import g, request

from errors import ApiError, ERR_FORBIDDEN, ERR_UNAUTHENTICATED

ROLES = {
    "BoardDirector",
    "RateAnalyst",
    "ProgramOperator",
    "CustomerService",
    "PortfolioManager",
    "BillingCoordinator",
    "FinanceController",
    "ComplianceOfficer",
    "UtilityLiaison",
}

ALL_ROLES = tuple(sorted(ROLES))


def require_roles(*allowed):
    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            uid = request.headers.get("X-User-ID")
            role = request.headers.get("X-User-Role")
            if not uid or not role or role not in ROLES:
                raise ApiError(ERR_UNAUTHENTICATED, 401,
                               "Missing or malformed X-User-Role / X-User-ID headers, or undeclared role")
            if role not in allowed:
                raise ApiError(ERR_FORBIDDEN, 403,
                               f"Role {role} is not authorized for this endpoint")
            g.user_id = uid
            g.user_role = role
            return fn(*args, **kwargs)
        return wrapper
    return deco
