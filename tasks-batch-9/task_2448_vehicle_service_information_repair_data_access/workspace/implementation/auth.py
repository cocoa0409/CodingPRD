"""Authentication, role authorization and scope confinement -- PRD 2.1 / 2.7."""

from flask import request

from errors import err

ROLES = ("PlatformAdmin", "ContentPublisher", "ComplianceOfficer", "ShopManager", "Technician")


def authenticate(allowed_roles):
    """Ladder rungs 1 and 2: header authentication then role authorization."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise err("ERR_UNAUTHENTICATED")
    if role not in allowed_roles:
        raise err("ERR_UNAUTHORIZED")
    return user_id, role


def require_shop_scope(role, user_id, shop_id):
    """Ladder rung 3: a ShopManager's X-User-ID must equal the addressed Shop.id."""
    if role == "ShopManager" and shop_id != user_id:
        raise err("ERR_CROSS_SHOP_ACCESS")


def require_seat_holder(role, user_id, technician_id):
    """Ladder rung 4: a Technician's X-User-ID must equal the seat's technician_id."""
    if role == "Technician" and technician_id != user_id:
        raise err("ERR_NOT_SEAT_HOLDER")
