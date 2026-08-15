"""Auth middleware (PRD 2.1, validation layers 1-2). Every request carries
X-User-ID and X-User-Role; missing headers or an undeclared role yields
ERR_UNAUTHENTICATED (401); a declared role not listed for the endpoint yields
ERR_UNAUTHORIZED (403)."""

from functools import wraps

from flask import request

from errors import fail

ROLES = [
    "DealershipAdmin",
    "SalesConsultant",
    "Customer",
    "SiteEvaluator",
    "InstallationManager",
    "TransportCoordinator",
    "LenderAgent",
    "ServiceManager",
    "Appraiser",
]

ALL_ROLES = tuple(ROLES)


def require(*roles):
    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            uid = request.headers.get("X-User-ID")
            role = request.headers.get("X-User-Role")
            if not uid or not role or role not in ROLES:
                fail("ERR_UNAUTHENTICATED",
                     "X-User-ID and X-User-Role headers are required and the role must be declared")
            if roles and role not in roles:
                fail("ERR_UNAUTHORIZED", "Role not permitted on this endpoint")
            kwargs["actor_id"] = uid
            kwargs["actor_role"] = role
            return fn(*args, **kwargs)

        return wrapper

    return deco
