"""Authentication, role authorization and SellerUser ownership scope.

PRD 2.1 / 2.5 groups 1, 2 and 5.
"""

import functools

from flask import request

from errors import ApiError

ROLES = (
    "SellerUser",
    "CounterpartyAnalyst",
    "QCReviewer",
    "LockDeskTrader",
    "PurchaseReviewer",
    "PlatformAdmin",
)

USER_ID_HEADER = "X-User-ID"
USER_ROLE_HEADER = "X-User-Role"


def user_id():
    return (request.headers.get(USER_ID_HEADER) or "").strip()


def user_role():
    return (request.headers.get(USER_ROLE_HEADER) or "").strip()


def is_seller_user():
    return user_role() == "SellerUser"


def endpoint(*allowed_roles):
    """Group 1 (authentication) then group 2 (role authorization)."""
    allowed = tuple(allowed_roles)

    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            if not user_id() or not user_role():
                raise ApiError("ERR_UNAUTHENTICATED")
            if user_role() not in allowed:
                raise ApiError("ERR_FORBIDDEN_ROLE")
            return fn(*args, **kwargs)

        wrapper._allowed_roles = allowed
        return wrapper

    return decorator


def require_scope(owning_seller_id):
    """Group 5: a SellerUser may only address its own seller's resources."""
    if is_seller_user() and owning_seller_id != user_id():
        raise ApiError("ERR_SELLER_SCOPE_VIOLATION")


def scope_seller_filter(requested_seller_id):
    """Narrow a collection to the acting SellerUser's own seller_id."""
    if not is_seller_user():
        return requested_seller_id
    if requested_seller_id is not None and requested_seller_id != user_id():
        raise ApiError("ERR_SELLER_SCOPE_VIOLATION")
    return user_id()
