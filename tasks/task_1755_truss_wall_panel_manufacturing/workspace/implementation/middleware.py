"""Auth header extraction, role checking, and customer-ownership scope.

Validation priority (PRD section 2.7):
  1. authentication (ERR_UNAUTHENTICATED 401)
  2. role authorization (ERR_FORBIDDEN_ROLE 403)
  3. customer-ownership scope (ERR_FORBIDDEN_OWNERSHIP 403)
  4. existence (ERR_NOT_FOUND 404)
  5. request schema (ERR_INVALID_REQUEST 400)
  6. OCC version checks (412)
  then state-machine guards and business rules.
"""

from flask import request

import db
from errors import (
    ApiError,
    ERR_UNAUTHENTICATED,
    ERR_FORBIDDEN_ROLE,
    ERR_FORBIDDEN_OWNERSHIP,
    ERR_NOT_FOUND,
)

ROLES = [
    "PlantManager",
    "DesignEngineer",
    "ProductionPlanner",
    "InventoryManager",
    "ShopFloorLead",
    "ShippingCoordinator",
    "ClaimsAdjuster",
    "CustomerContact",
]

ENTITY_BACKED = {
    "DesignEngineer": db.engineers,        # X-User-ID is the Engineer id
    "CustomerContact": db.customers,       # X-User-ID is the CustomerAccount id
}

# Roles allowed to use every GET endpoint; CustomerContact is excluded from
# several read surfaces entirely (endpoint table column 4).
ALL_ROLES = list(ROLES)
INTERNAL_ROLES = [r for r in ROLES if r != "CustomerContact"]


def authenticate():
    """Priority 1: headers present, role declared, entity-backed id resolves."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role:
        raise ApiError(ERR_UNAUTHENTICATED, 401, "missing X-User-ID or X-User-Role header")
    if role not in ROLES:
        raise ApiError(ERR_UNAUTHENTICATED, 401, f"unknown role: {role}")
    backing = ENTITY_BACKED.get(role)
    if backing is not None and uid not in backing:
        raise ApiError(ERR_UNAUTHENTICATED, 401, "entity-backed identity does not resolve")
    return uid, role


def require_role(role, allowed):
    """Priority 2: role in the endpoint's roles list."""
    if role not in allowed:
        raise ApiError(ERR_FORBIDDEN_ROLE, 403, f"role {role} is not authorized for this operation")


def require_ownership(role, uid, customer_id):
    """Priority 3: CustomerContact acting outside its own customer scope."""
    if role == "CustomerContact" and customer_id != uid:
        raise ApiError(ERR_FORBIDDEN_OWNERSHIP, 403, "customer contact acting outside its own customer scope")


def get_or_404(collection, rid, what="resource"):
    """Priority 4: path/body identifier existence."""
    if not isinstance(rid, str) or rid not in collection:
        raise ApiError(ERR_NOT_FOUND, 404, f"{what} not found")
    return collection[rid]
