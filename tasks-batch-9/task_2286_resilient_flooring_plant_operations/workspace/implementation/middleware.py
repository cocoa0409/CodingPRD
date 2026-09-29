"""Authentication (PRD 2.1 band 1) and authorization (band 2) helpers."""

from flask import g, request

from db import NOT_FOUND_ERROR, db
from errors import ApiError

ROLES = (
    "PlantAdmin",
    "Formulator",
    "TechnicalDirector",
    "QaTechnician",
    "ProductionPlanner",
    "WarrantyAdjuster",
    "Distributor",
)

USER_ID_HEADER = "X-User-ID"
USER_ROLE_HEADER = "X-User-Role"


def authenticate():
    """Band 1.  Both headers must be present, non-empty and the role known."""
    user_id = request.headers.get(USER_ID_HEADER)
    role = request.headers.get(USER_ROLE_HEADER)
    if role is None:
        # tolerate the abbreviated spelling; PRD 2.1 names X-User-Role
        role = request.headers.get("X-Role")
    if user_id is None or user_id.strip() == "":
        raise ApiError("ERR_UNAUTHENTICATED")
    if role is None or role.strip() == "":
        raise ApiError("ERR_UNAUTHENTICATED")
    if role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED")
    g.user_id = user_id
    g.role = role


def user_id():
    return g.user_id


def role():
    return g.role


def authorize(*allowed):
    """Band 2 (V-RBAC-1)."""
    if g.role not in allowed:
        raise ApiError("ERR_UNAUTHORIZED")


def require_role(expected):
    """Band 2 (V-RBAC-2): payload-dependent role narrowing."""
    if g.role != expected:
        raise ApiError("ERR_UNAUTHORIZED")


def find(collection, row_id):
    """Band 4/5: path or body foreign key existence."""
    store = getattr(db, collection)
    row = store.get(row_id) if isinstance(row_id, str) else None
    if row is None:
        raise ApiError(NOT_FOUND_ERROR[collection])
    return row


def owner_guard(distributor_id):
    """Bands 6: V-OWN-1 / V-OWN-2 for the Distributor role."""
    if g.role == "Distributor" and g.user_id != distributor_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")
