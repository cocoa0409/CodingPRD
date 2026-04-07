"""Authentication and RBAC middleware."""

from flask import request, g
from errors import AppError, ERR_AUTH_HEADER_MISSING, ERR_FORBIDDEN, ERR_NOT_SHOP_OWNER, ERR_NOT_ORDER_OWNER
from config import VALID_ROLES
import db


def require_auth():
    """Extract and validate X-User-ID and X-User-Role headers. Store in flask.g."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in VALID_ROLES:
        raise AppError(ERR_AUTH_HEADER_MISSING, "Missing or invalid auth headers.", 400)
    g.user_id = user_id
    g.role = role


def require_role(*allowed_roles):
    """Check the current user's role is in the allowed set. PlatformAdmin always passes (hierarchical override)."""
    if g.role == "PlatformAdmin":
        return
    if g.role not in allowed_roles:
        raise AppError(ERR_FORBIDDEN, f"Role {g.role} is not authorized.", 403)


def require_shop_owner(shop):
    """Seller must own the shop."""
    if g.role == "Seller" and shop["owner_id"] != g.user_id:
        raise AppError(ERR_NOT_SHOP_OWNER, "You do not own this shop.", 403)


def require_order_owner(order):
    """Customer must own the order."""
    if g.role == "Customer" and order["customer_id"] != g.user_id:
        raise AppError(ERR_NOT_ORDER_OWNER, "You do not own this order.", 403)
