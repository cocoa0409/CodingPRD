"""Auth middleware (PRD §2.1) and request-body helper.

Every request must carry X-User-ID and X-User-Role. A request missing either
header, or carrying a role name outside the declared set, is rejected with
ERR_UNAUTHENTICATED (401). A request whose role is not on the endpoint's
authorized list is rejected with ERR_UNAUTHORIZED_ROLE (403).
"""
import functools

from flask import request

from errors import (
    ApiError,
    ERR_UNAUTHENTICATED,
    ERR_UNAUTHORIZED_ROLE,
    ERR_VALIDATION,
)

ROLES = {
    "ClientContact",
    "IntakeCoordinator",
    "CaptionEditor",
    "ADProducer",
    "QCSpecialist",
    "Scheduler",
    "Stenographer",
    "OperationsManager",
}

ALL_ROLES = sorted(ROLES)


def body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError(ERR_VALIDATION, 400, "Request body must be a JSON object")
    return data


def authenticate():
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise ApiError(
            ERR_UNAUTHENTICATED,
            401,
            "Missing or invalid X-User-Role / X-User-ID headers",
        )
    return user_id, role


def guarded(roles):
    """Decorator: priority 1 (authentication) then priority 2 (role)."""
    def deco(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            user_id, role = authenticate()
            if role not in roles:
                raise ApiError(
                    ERR_UNAUTHORIZED_ROLE,
                    403,
                    f"Role {role} is not authorized for this endpoint",
                )
            return fn(*args, _user_id=user_id, _role=role, **kwargs)
        return wrapper
    return deco
