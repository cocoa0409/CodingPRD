"""Auth header extraction and role checks."""
from flask import request
from errors import (
    AppError,
    raise_err,
    ERR_UNAUTHENTICATED,
    ERR_UNAUTHORIZED,
    ERR_NOT_SHOP_OWNER,
)

VALID_ROLES = {"Seller", "Buyer", "PlatformAdmin"}


def get_auth():
    """Return (user_id, user_role) after validating headers. Raises ERR_UNAUTHENTICATED."""
    user_id = request.headers.get("X-User-ID")
    user_role = request.headers.get("X-User-Role")
    if not user_id or not user_role or user_role not in VALID_ROLES:
        raise_err(ERR_UNAUTHENTICATED, "missing or unknown auth headers")
    return user_id, user_role


def require_role(user_role, allowed):
    if user_role not in allowed:
        raise_err(ERR_UNAUTHORIZED, f"role {user_role} not authorized")


def require_shop_owner(user_id, user_role, shop_id):
    """Seller ownership check: X-User-ID must equal shop_id."""
    if user_role == "Seller" and user_id != shop_id:
        raise_err(ERR_NOT_SHOP_OWNER, "seller does not own this shop")


def require_buyer_owner(user_id, user_role, order_buyer_id):
    """Buyer ownership check: X-User-ID must equal order.buyer_id."""
    if user_role == "Buyer" and user_id != order_buyer_id:
        raise_err(ERR_NOT_SHOP_OWNER, "buyer does not own this order")
