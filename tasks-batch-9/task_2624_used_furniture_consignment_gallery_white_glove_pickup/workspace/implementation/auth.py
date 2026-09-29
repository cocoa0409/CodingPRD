"""Authentication, authorization and ownership scoping (PRD 2.1)."""

from flask import request

from errors import fail

ROLES = (
    "Consignor",
    "Buyer",
    "IntakeAppraiser",
    "FloorOperator",
    "LogisticsCoordinator",
    "GalleryManager",
    "SystemOperator",
)


def identity():
    """Ladder position 1: both headers present and the role declared."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or role is None:
        fail("ERR_UNAUTHENTICATED")
    if not str(user_id).strip():
        fail("ERR_UNAUTHENTICATED")
    if role not in ROLES:
        fail("ERR_UNAUTHENTICATED")
    return str(user_id), role


def require(*allowed_roles):
    """Ladder positions 1 then 2. Returns (user_id, role)."""
    user_id, role = identity()
    if role not in allowed_roles:
        fail("ERR_UNAUTHORIZED")
    return user_id, role


def deny_unless(condition):
    """Ownership scoping refusal (PRD 2.1)."""
    if not condition:
        fail("ERR_UNAUTHORIZED")


def scope_consignor(role, user_id, consignor_id):
    """A Consignor may only reach rows whose consignor_id is their own id."""
    if role == "Consignor":
        deny_unless(consignor_id is not None and consignor_id == user_id)


def scope_buyer(role, user_id, buyer_id):
    if role == "Buyer":
        deny_unless(buyer_id is not None and buyer_id == user_id)
