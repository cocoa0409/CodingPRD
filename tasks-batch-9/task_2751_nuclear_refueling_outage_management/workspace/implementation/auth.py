"""Authentication / RBAC (PRD 2.1, order of rejection ranks 1 and 2)."""
import functools

from flask import request

from errors import api_error

ROLES = (
    "StationAdmin",
    "OutageDirector",
    "OutagePlanner",
    "ReactorEngineer",
    "ContractorCoordinator",
    "AccessAuthority",
    "RadProtectionPlanner",
    "RadProtectionManager",
    "RegulatoryAffairs",
)

ALL_ROLES = ROLES


def current_user_id():
    return request.headers.get("X-User-ID")


def current_role():
    return request.headers.get("X-User-Role")


def authenticate():
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or str(user_id).strip() == "":
        raise api_error("ERR_UNAUTHENTICATED", "X-User-ID header is required.")
    if role is None or str(role).strip() == "":
        raise api_error("ERR_UNAUTHENTICATED", "X-User-Role header is required.")
    if role not in ROLES:
        raise api_error("ERR_UNAUTHENTICATED", "X-User-Role names an unknown role.")
    return user_id, role


def authorize(*allowed):
    """Decorator: authenticate, then check the acting role against the endpoint."""
    allowed_set = tuple(allowed) if allowed else ALL_ROLES

    def outer(fn):
        @functools.wraps(fn)
        def inner(*args, **kwargs):
            _user_id, role = authenticate()
            if role not in allowed_set:
                raise api_error(
                    "ERR_UNAUTHORIZED",
                    "Role %s is not authorized for this endpoint." % role,
                )
            return fn(*args, **kwargs)

        return inner

    return outer
