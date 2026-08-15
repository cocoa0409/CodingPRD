"""Auth header extraction + role gating.

PRD §2.1: every request carries X-User-ID and X-User-Role; missing/empty
-> ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER (400). Role not permitted
-> ERR_INSUFFICIENT_PERMISSIONS (403).

Eight roles, spelled exactly: ChandlerOpsManager, ChandlerSalesRep,
WarehouseSupervisor, VesselCateringOfficer, PortCustomsOfficer,
FinanceController, ShipAgentClerk, QualityAssuranceLead.

Entity-backed identity:
  - VesselCateringOfficer: X-User-ID is the acting VesselCall.id
  - ShipAgentClerk:        X-User-ID is the acting ShipAgent.id
The other six roles are opaque operator identifiers.
"""
from functools import wraps

from flask import request

from errors import err_missing_context, err_insufficient_permissions

ALL_ROLES = (
    "ChandlerOpsManager",
    "ChandlerSalesRep",
    "WarehouseSupervisor",
    "VesselCateringOfficer",
    "PortCustomsOfficer",
    "FinanceController",
    "ShipAgentClerk",
    "QualityAssuranceLead",
)


def get_context():
    """Return (user_id, role) or raise ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or str(user_id).strip() == "":
        raise err_missing_context()
    if role is None or str(role).strip() == "":
        raise err_missing_context()
    return user_id, role


def require_roles(*roles):
    """Decorator: enforce headers present (priority 1) then role membership
    (priority 2). Entity-backed ownership checks are performed inside the
    route handlers once the target entity has been loaded."""
    allowed = set(roles)

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_id, role = get_context()
            if allowed and role not in allowed:
                raise err_insufficient_permissions()
            return fn(user_id, role, *args, **kwargs)

        return wrapper

    return decorator


def require_any_authenticated(fn):
    """GET endpoints: open to all eight roles, but headers must be present."""
    @wraps(fn)
    def wrapper(*args, **kwargs):
        user_id, role = get_context()
        if role not in ALL_ROLES:
            raise err_insufficient_permissions()
        return fn(user_id, role, *args, **kwargs)

    return wrapper
