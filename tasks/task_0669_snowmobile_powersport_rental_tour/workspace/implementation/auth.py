"""Authentication and RBAC (PRD §2.1, SCAFFOLD §1.4 priorities 1-3, §1.7).

Two mandatory headers: X-User-ID (acting principal) and X-User-Role (capacity).
Roles, spelled precisely: Anonymous, Member, Guide, DispatchOperator, PlatformAdmin.
"""
from flask import request

from errors import (
    err,
    ERR_UNAUTHENTICATED,
    ERR_UNAUTHORIZED,
)

VALID_ROLES = {"Anonymous", "Member", "Guide", "DispatchOperator", "PlatformAdmin"}


class Principal:
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role


def authenticate():
    """Validate X-User-ID and X-User-Role headers (priority 1). Returns Principal.

    Missing/malformed either header -> ERR_UNAUTHENTICATED. A role value outside
    the recognized set is malformed.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not isinstance(user_id, str) or user_id.strip() == "":
        err(ERR_UNAUTHENTICATED, "Missing or malformed X-User-ID header")
    if not role or role not in VALID_ROLES:
        err(ERR_UNAUTHENTICATED, "Missing or malformed X-User-Role header")
    return Principal(user_id.strip(), role)


def authorize(principal, permitted_roles):
    """Role-authorization gate (priority 2). permitted_roles is a set of role names."""
    if principal.role not in permitted_roles:
        err(ERR_UNAUTHORIZED, f"Role {principal.role} is not permitted for this operation")
