"""Authentication / authorisation (PRD 2.1, ladder tiers 1-2)."""
from functools import wraps

from flask import g, request

import errors

ROLE_CUSTOMER = "Customer"
ROLE_SCHEDULER = "PlantScheduler"
ROLE_OPERATOR = "PlantOperator"
ROLE_QUALITY = "QualityManager"
ROLE_ADMIN = "FacilityAdmin"

ROLES = (ROLE_CUSTOMER, ROLE_SCHEDULER, ROLE_OPERATOR, ROLE_QUALITY, ROLE_ADMIN)


def authenticate():
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or str(user_id).strip() == "":
        raise errors.unauthenticated("X-User-ID header is missing or empty.")
    if role is None or str(role).strip() == "":
        raise errors.unauthenticated("X-User-Role header is missing or empty.")
    if role not in ROLES:
        raise errors.unauthenticated("X-User-Role names an unrecognised role.")
    return user_id, role


def endpoint(roles):
    """Decorator: tier 1 authentication then tier 2 authorisation."""
    allowed = tuple(roles)

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_id, role = authenticate()
            if role not in allowed:
                raise errors.unauthorized()
            g.user_id = user_id
            g.role = role
            return fn(*args, **kwargs)

        return wrapper

    return decorator


def is_customer():
    return getattr(g, "role", None) == ROLE_CUSTOMER


def acting_user():
    return getattr(g, "user_id", None)


def require_owner(customer_id):
    """Tier 6 ownership check (PRD 2.1 / 2.6)."""
    if is_customer() and customer_id != acting_user():
        raise errors.not_owner()
