"""Auth middleware: header extraction, role authorization (PRD 2.1, 2.9)."""

from functools import wraps

from flask import request

from errors import ApiError, ERR_UNAUTHENTICATED, ERR_UNAUTHORIZED

VALID_ROLES = {
    "PlatformAdmin",
    "ClientAdmin",
    "OperationsManager",
    "DispatchCoordinator",
    "Broker",
    "QCReviewer",
    "BillingClerk",
    "ComplianceOfficer",
}


def authenticate():
    """Priority 1: X-User-Role and X-User-ID headers present and non-empty."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role:
        raise ApiError(
            ERR_UNAUTHENTICATED,
            "Missing or empty X-User-ID or X-User-Role header",
            401,
        )
    return user_id, role


def allowed(*roles):
    """Decorator: authenticate (priority 1) then authorize role (priority 2)."""

    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_id, role = authenticate()
            if role not in roles:
                raise ApiError(
                    ERR_UNAUTHORIZED,
                    f"Role {role} is not permitted to invoke this endpoint",
                    403,
                )
            return fn(user_id, role, *args, **kwargs)

        return wrapper

    return deco
