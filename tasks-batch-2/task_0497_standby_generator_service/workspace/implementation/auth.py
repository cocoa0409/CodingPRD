"""Auth / RBAC helpers (PRD §2.1).

Every request carries X-User-ID and X-User-Role. Five roles spelled exactly:
Anonymous, Customer, Technician, ServiceManager, ComplianceOfficer.
"""
from flask import request

from errors import err

ROLES = {"Anonymous", "Customer", "Technician", "ServiceManager", "ComplianceOfficer"}


class Principal:
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role


def get_principal():
    """Extract & validate headers. Missing either -> ERR_UNAUTHENTICATED.

    Note: an unrecognized role string still counts as 'present' for the auth
    check; RBAC (role-permitted) is enforced separately per endpoint and will
    reject it with ERR_FORBIDDEN since it is not in any endpoint's allowed set.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role:
        raise err("ERR_UNAUTHENTICATED", "Missing X-User-ID / X-User-Role headers")
    return Principal(user_id, role)


def require_roles(principal, allowed):
    """ERR_FORBIDDEN if the acting role is not permitted for the operation."""
    if principal.role not in allowed:
        raise err("ERR_FORBIDDEN", f"Role {principal.role} not permitted")
