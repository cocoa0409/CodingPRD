"""Auth: X-User-ID / X-User-Role header extraction and role gating (PRD §2.1)."""
from functools import wraps

from flask import request, g

import errors
from errors import ApiError

ROLES = [
    "OrderManager",
    "ComplianceOfficer",
    "WarehouseOperator",
    "QualityAssuranceLead",
    "BillingClerk",
    "ContractAdministrator",
]

ALL_ROLES = list(ROLES)


def get_context():
    """Validate the two auth headers; returns (user_id, role)."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not isinstance(uid, str) or not uid.strip():
        raise ApiError(errors.ERR_AUTH[0], errors.ERR_AUTH[1],
                       "X-User-ID header is required and must be a non-empty string")
    if not role or role not in ROLES:
        raise ApiError(errors.ERR_AUTH[0], errors.ERR_AUTH[1],
                       "X-User-Role header is required and must name a recognized role")
    g.user_id = uid
    g.user_role = role
    return uid, role


def require_roles(allowed):
    role = getattr(g, "user_role", None)
    if role is None:
        get_context()
        role = g.user_role
    if role not in allowed:
        raise ApiError(errors.ERR_UNAUTHORIZED_ROLE[0], errors.ERR_UNAUTHORIZED_ROLE[1],
                       "Role %s is not permitted on this endpoint" % role)


def endpoint(roles):
    """Decorator: auth header validation (priority 1) then RBAC (priority 2)."""
    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            get_context()
            require_roles(roles)
            return fn(*args, **kwargs)
        return wrapper
    return deco
