"""Auth header extraction and RBAC. PRD 2.1.

Every request must carry X-User-ID and X-User-Role. The four roles, spelled
exactly: SchoolAdmin, BillingAdmin, Instructor, Parent.
"""
from flask import request

from errors import err, ERR_MISSING_AUTH_CONTEXT, ERR_INSUFFICIENT_PERMISSIONS

VALID_ROLES = {"SchoolAdmin", "BillingAdmin", "Instructor", "Parent"}


class Principal:
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role


def get_principal():
    """PRD 2.1: if either header is missing or malformed, reject with
    ERR_MISSING_AUTH_CONTEXT (401) before any other processing."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or role is None:
        err(ERR_MISSING_AUTH_CONTEXT, "Missing X-User-ID or X-User-Role header")
    if not isinstance(user_id, str) or user_id.strip() == "":
        err(ERR_MISSING_AUTH_CONTEXT, "Malformed X-User-ID header")
    if role not in VALID_ROLES:
        err(ERR_MISSING_AUTH_CONTEXT, "Malformed X-User-Role header")
    return Principal(user_id, role)


def require_roles(principal, allowed_roles):
    """PRD 2.1: when headers are present but the role is not permitted, reject
    with ERR_INSUFFICIENT_PERMISSIONS (403)."""
    if principal.role not in allowed_roles:
        err(ERR_INSUFFICIENT_PERMISSIONS,
            "Role %s not permitted for this operation" % principal.role)
