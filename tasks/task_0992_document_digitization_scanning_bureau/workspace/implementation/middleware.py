"""Auth middleware: X-User-ID / X-User-Role extraction and role checking per SCAFFOLD §1.4 / PRD §2.1."""

from functools import wraps

from flask import request

from errors import ApiError, ERR_UNAUTHENTICATED, ERR_FORBIDDEN

ROLES = {
    "PlatformAdmin",
    "IntakeClerk",
    "PrepTechnician",
    "ScanOperator",
    "QAReviewer",
    "Indexer",
    "DestructionSpecialist",
    "ComplianceOfficer",
    "BillingClerk",
    "ClientUser",
}


def get_auth():
    """Extract and validate auth headers. Returns (user_id, role). Raises ApiError 401."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role:
        raise ApiError(ERR_UNAUTHENTICATED, "Missing X-User-ID or X-User-Role header", 401)
    if role not in ROLES:
        raise ApiError(ERR_UNAUTHENTICATED, "Unrecognized role", 401)
    return user_id, role


def require_roles(*allowed_roles):
    """Decorator factory: enforce authentication then role authorization."""

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_id, role = get_auth()
            if role not in allowed_roles:
                raise ApiError(ERR_FORBIDDEN, "Role not permitted for this endpoint", 403)
            return fn(*args, _user_id=user_id, _role=role, **kwargs)

        return wrapper

    return decorator


def check_client_user_scope(user_id, role, client_id):
    """ClientUser may only act within its own client subtree (X-User-ID == client_id)."""
    if role == "ClientUser" and user_id != client_id:
        raise ApiError(ERR_FORBIDDEN, "ClientUser acting outside its own client subtree", 403)
