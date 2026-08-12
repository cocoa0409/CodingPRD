"""Auth (PRD §2.1): X-User-ID + X-User-Role headers, eight declared roles."""
from functools import wraps

from flask import g, request

from errors import unauthenticated, unauthorized_role

ROLES = {
    "ProgramDirector",
    "DesignManager",
    "PermitCoordinator",
    "ProcurementLead",
    "GCVendor",
    "SiteSuperintendent",
    "OperationsLead",
    "FinanceController",
}

ALL_ROLES = sorted(ROLES)


def authed(roles):
    """Validation steps 1-2: authentication, then endpoint role authorization."""
    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            uid = request.headers.get("X-User-ID")
            role = request.headers.get("X-User-Role")
            if not uid or not role or role not in ROLES:
                unauthenticated()
            if role not in roles:
                unauthorized_role()
            g.user_id = uid
            g.role = role
            return fn(*args, **kwargs)
        return wrapper
    return deco
