"""Auth header extraction and RBAC (PRD §2.1, validations priority 1-2)."""

import functools

from flask import g, request

from errors import ApiError

ROLES = (
    "Developer",
    "RouteAnalyst",
    "CommissionStaff",
    "HearingExaminer",
    "Landowner",
    "FederalPermitOfficer",
    "ComplianceMonitor",
)

ALL_ROLES = list(ROLES)


def endpoint(roles=None):
    """Decorator enforcing header presence then endpoint authorization."""

    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            user_id = request.headers.get("X-User-ID")
            role = request.headers.get("X-User-Role")
            if user_id is None or str(user_id).strip() == "":
                raise ApiError("ERR_UNAUTHENTICATED", "X-User-ID header missing or empty.")
            if role is None or str(role).strip() == "":
                raise ApiError("ERR_UNAUTHENTICATED", "X-User-Role header missing or empty.")
            if role not in ROLES:
                raise ApiError("ERR_UNAUTHORIZED", "Unknown role '%s'." % role)
            if roles is not None and role not in roles:
                raise ApiError("ERR_UNAUTHORIZED", "Role '%s' may not perform this operation." % role)
            g.user_id = user_id
            g.role = role
            return fn(*args, **kwargs)

        return wrapper

    return decorator
