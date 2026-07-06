"""Auth (X-User-Role + X-User-ID) and pagination helpers."""
from flask import request
from errors import ApiError, unauthenticated, unauthorized, invalid_request
from db import DB

VALID_ROLES = {"Anonymous", "Customer", "ShopStaff", "Horticulturist", "DeliveryDriver", "Manager"}
ENTITY_BACKED_ROLES = {"Customer", "DeliveryDriver"}


def auth_context():
    """Return (role, user_id). Raises ERR_UNAUTHENTICATED for missing/invalid role
    or missing X-User-ID on entity-backed roles."""
    role = request.headers.get("X-User-Role")
    if not role or role not in VALID_ROLES:
        raise unauthenticated("X-User-Role missing or invalid")
    user_id = request.headers.get("X-User-ID")
    if role in ENTITY_BACKED_ROLES:
        if not user_id:
            raise unauthenticated("X-User-ID required for entity-backed role")
    return role, user_id


def require_role(role: str, allowed):
    if role not in allowed:
        raise unauthorized(f"role {role} not permitted")


def require_customer_owner(role: str, user_id: str, owner_customer_id: str):
    """Customer-owned check. Non-Customer roles skip this check (RBAC decides
    whether they can access at all, but not ownership)."""
    if role == "Customer":
        if user_id != owner_customer_id:
            raise unauthorized("Customer does not own this resource")


def require_customer_or_manager_owner(role: str, user_id: str, owner_customer_id: str):
    """For endpoints where both Customer (owner) and Manager can act."""
    if role == "Customer":
        if user_id != owner_customer_id:
            raise unauthorized("Customer does not own this resource")


def require_driver_owner(role: str, user_id: str, assignment_driver_id: str):
    if role == "DeliveryDriver":
        if user_id != assignment_driver_id:
            raise unauthorized("DeliveryDriver does not own this delivery")


def require_json():
    if request.method in ("POST", "PUT", "PATCH"):
        if not request.is_json and request.data:
            raise invalid_request("Content-Type must be application/json")
    return request.get_json(silent=True) or {}


def parse_pagination(args):
    """Read limit/offset from query string. limit default 10 (min 1, max 100),
    offset default 0. Out-of-range -> ERR_INVALID_REQUEST."""
    limit = args.get("limit", 10)
    offset = args.get("offset", 0)
    try:
        limit = int(limit)
    except (TypeError, ValueError):
        raise invalid_request("limit must be an integer")
    try:
        offset = int(offset)
    except (TypeError, ValueError):
        raise invalid_request("offset must be an integer")
    if limit < 1 or limit > 100:
        raise invalid_request("limit must be in [1,100]")
    if offset < 0:
        raise invalid_request("offset must be >= 0")
    return limit, offset


def sort_by_created(items):
    return sorted(items, key=lambda x: (x.get("created_at", ""), x.get("id", "")))


def paginate(items, limit, offset):
    total = len(items)
    return items[offset:offset + limit], total
