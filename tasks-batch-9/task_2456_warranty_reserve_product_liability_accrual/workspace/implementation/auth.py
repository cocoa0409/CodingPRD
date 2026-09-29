"""Authentication and RBAC (PRD §2.1, validation rungs 1-2)."""

from flask import g, request

from errors import fail

ROLES = (
    "WarrantyAnalyst",
    "ReserveController",
    "QualityEngineer",
    "Actuary",
    "SupplierRep",
    "PlatformAdmin",
)

USER_ID_HEADER = "X-User-ID"
USER_ROLE_HEADER = "X-User-Role"


def authenticate(allowed_roles):
    """Rung 1 then rung 2.  Stores the caller identity on ``flask.g``."""
    user_id = request.headers.get(USER_ID_HEADER)
    role = request.headers.get(USER_ROLE_HEADER)
    if user_id is None or role is None or user_id == "" or role == "":
        fail("ERR_UNAUTHENTICATED")
    if role not in ROLES:
        fail("ERR_UNAUTHENTICATED")
    g.user_id = user_id
    g.role = role
    if role not in allowed_roles:
        fail("ERR_FORBIDDEN_ROLE")
    return user_id, role


def caller_id():
    return g.get("user_id")


def caller_role():
    return g.get("role")
