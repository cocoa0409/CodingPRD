"""Authentication and role authorization (PRD 2.1, 2.8 priorities 1-2).

Every request carries X-User-ID (opaque) and X-User-Role (one of five
declared roles). Missing/invalid -> ERR_UNAUTHENTICATED (401). A role not in
the endpoint's authorized list -> ERR_FORBIDDEN_ROLE (403).
"""
from functools import wraps

from flask import request

from errors import ERR_FORBIDDEN_ROLE, ERR_UNAUTHENTICATED, raise_error

ROLES = [
    "BrokerPrincipal",
    "ListingAgent",
    "BuyerAgent",
    "EscrowOfficer",
    "FacilityScheduler",
]
ALL_ROLES = list(ROLES)


def current_role():
    return request.headers.get("X-User-Role")


def current_user_id():
    return request.headers.get("X-User-ID")


def require_roles(allowed):
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            role = current_role()
            uid = current_user_id()
            if not role or not uid or role not in ROLES:
                raise_error(
                    ERR_UNAUTHENTICATED,
                    "X-User-ID and a declared X-User-Role header are required",
                )
            if role not in allowed:
                raise_error(
                    ERR_FORBIDDEN_ROLE,
                    f"role {role} is not authorized for this operation",
                )
            return fn(*args, **kwargs)

        return wrapper

    return decorator
