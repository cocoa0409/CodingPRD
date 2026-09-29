"""Auth header extraction and RBAC (PRD §2.1, ladder steps 1, 2, 6)."""
import functools

from flask import g, request

from errors import ApiError

ROLES = ("SellerOperator", "FcOperator", "ClaimsAdjudicator", "MarketplaceAdmin")


def authenticate():
    """Ladder step 1 — header presence and role recognition."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or role is None:
        raise ApiError("ERR_UNAUTHENTICATED", 401)
    if user_id.strip() == "" or role.strip() == "":
        raise ApiError("ERR_UNAUTHENTICATED", 401)
    if role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", 401)
    g.user_id = user_id
    g.role = role


def require_roles(*allowed):
    """Ladder step 2 — role authorization for the requested operation."""
    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            if g.role not in allowed:
                raise ApiError("ERR_FORBIDDEN_ROLE", 403)
            return fn(*args, **kwargs)
        return wrapper
    return decorator


def require_seller_scope(seller_account_id):
    """Ladder step 6 — SellerOperator ownership scope."""
    if g.role == "SellerOperator" and g.user_id != seller_account_id:
        raise ApiError("ERR_SELLER_SCOPE_VIOLATION", 403)


def require_fc_scope(fulfillment_center_id):
    """Ladder step 6 — FcOperator ownership scope."""
    if g.role == "FcOperator" and g.user_id != fulfillment_center_id:
        raise ApiError("ERR_FC_SCOPE_VIOLATION", 403)
