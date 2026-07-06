"""Auth/RBAC middleware: read X-User-ID and X-User-Role.

Per PRD §2.1 and SCAFFOLD validations: both headers required; role must be
one of {Customer, FulfillmentOps, BillingAdmin, PlatformAdmin} else
ERR_UNAUTHENTICATED. When role is Customer, X-User-ID is the id of an
existing Customer entity (used for ownership checks).
"""
from functools import wraps
from flask import request, g
from errors import ApiError, ERR_UNAUTHENTICATED, ERR_UNAUTHORIZED

VALID_ROLES = {"Customer", "FulfillmentOps", "BillingAdmin", "PlatformAdmin"}


def auth_required(*allowed_roles):
    """Decorator: enforce auth (priority 10) + role membership (priority 20).

    allowed_roles are the roles permitted for the endpoint. An empty tuple
    means any authenticated role is allowed (rare — only listing endpoints
    like /subscriptions if the role is any).
    """
    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_id = request.headers.get("X-User-ID")
            user_role = request.headers.get("X-User-Role")
            if not user_id or not user_role or user_role not in VALID_ROLES:
                raise ApiError(ERR_UNAUTHENTICATED,
                               "Missing or invalid X-User-ID / X-User-Role",
                               401)
            if allowed_roles and user_role not in allowed_roles:
                raise ApiError(ERR_UNAUTHORIZED,
                               "Role not permitted for this operation",
                               403)
            g.user_id = user_id
            g.user_role = user_role
            return fn(*args, **kwargs)
        return wrapper
    return deco
