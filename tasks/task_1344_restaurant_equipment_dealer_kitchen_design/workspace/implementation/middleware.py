"""Auth middleware: validates X-User-ID / X-User-Role headers and RBAC.

Per PRD section 2.1: every request carries X-User-ID and X-User-Role. Missing
or malformed (empty) headers -> ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER
(400). A role not authorized for the attempted operation ->
ERR_INSUFFICIENT_PERMISSIONS (403).

When the role is Customer, X-User-ID is the id of the acting Customer entity
and ownership checks compare a resource's customer FK to it. For the other
nine roles the id is opaque.
"""

from __future__ import annotations

from functools import wraps

from flask import request

import db
from errors import (
    ApiError,
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
    ERR_INSUFFICIENT_PERMISSIONS,
    HTTP_STATUS,
)

ROLES = {
    "PlatformAdmin",
    "ProjectManager",
    "KitchenDesigner",
    "SalesRep",
    "Customer",
    "PermitCoordinator",
    "FabricationLead",
    "LogisticsCoordinator",
    "StartupTechnician",
    "ServiceManager",
}


def get_auth() -> tuple[str, str]:
    """Extract and shape-validate the user-context headers."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if (
        user_id is None
        or str(user_id).strip() == ""
        or role is None
        or str(role).strip() == ""
    ):
        raise ApiError(
            ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            HTTP_STATUS[ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER],
            "X-User-ID or X-User-Role header is missing or malformed",
        )
    return user_id, role


def require_roles(*allowed: str):
    """Decorator: authenticate, then enforce role membership for the endpoint.

    Every request is serialized through a process-wide lock so OCC / capacity
    / credit checks are atomic under concurrent race tests.
    """

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            with db.LOCK:
                user_id, role = get_auth()
                if role not in ROLES or role not in allowed:
                    raise ApiError(
                        ERR_INSUFFICIENT_PERMISSIONS,
                        HTTP_STATUS[ERR_INSUFFICIENT_PERMISSIONS],
                        "Role is not authorized for this operation",
                    )
                return fn(*args, _user_id=user_id, _role=role, **kwargs)

        return wrapper

    return decorator


def require_customer_ownership(user_id: str, role: str, customer_id: str) -> None:
    """Entity-backed identity: a Customer caller may only touch resources whose
    owning customer FK equals X-User-ID."""
    if role == "Customer" and user_id != customer_id:
        raise ApiError(
            ERR_INSUFFICIENT_PERMISSIONS,
            HTTP_STATUS[ERR_INSUFFICIENT_PERMISSIONS],
            "Customer may access only its own resources",
        )
