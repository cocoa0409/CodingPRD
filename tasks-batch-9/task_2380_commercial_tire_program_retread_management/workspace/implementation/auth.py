"""Authentication, RBAC and scope checks (PRD §2.1, §2.11 steps 1-2 and 4-5)."""

from functools import wraps

from flask import g, request

import errors
from errors import fail

ROLES = (
    "DealerAdmin",
    "FleetManager",
    "TireTechnician",
    "CasingInspector",
    "PlantScheduler",
    "ComplianceOfficer",
    "BillingClerk",
    "DispatchCoordinator",
)


def endpoint(*allowed_roles):
    """Validation steps 1 and 2: authentication then endpoint authorisation."""

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_id = request.headers.get("X-User-ID")
            role = request.headers.get("X-User-Role")
            if not user_id or not role or role not in ROLES:
                fail(errors.ERR_UNAUTHENTICATED)
            if role not in allowed_roles:
                fail(errors.ERR_UNAUTHORIZED)
            g.user_id = user_id
            g.role = role
            return fn(*args, **kwargs)

        return wrapper

    return decorator


def is_fleet_manager():
    return g.role == "FleetManager"


def fleet_scope(fleet_account_id):
    """Validation step 4: a FleetManager acts only within its own fleet."""
    if is_fleet_manager() and fleet_account_id != g.user_id:
        fail(errors.ERR_FLEET_SCOPE_VIOLATION)


def scope_filter_value(requested):
    """For list endpoints: a FleetManager may only ask about its own fleet."""
    if is_fleet_manager():
        if requested is not None and requested != g.user_id:
            fail(errors.ERR_FLEET_SCOPE_VIOLATION)
        return g.user_id
    return requested
