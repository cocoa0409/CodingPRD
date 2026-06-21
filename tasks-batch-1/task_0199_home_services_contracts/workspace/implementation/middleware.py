"""Auth header extraction and role checking (PRD §2.1).

Two mandatory headers: X-User-ID identifies the acting user, X-User-Role declares
the role. Recognized roles: ContractAdmin, Dispatcher, Technician, Customer.
Missing either header, or an unknown role value -> ERR_UNAUTHENTICATED.
Role recognized but not permitted -> ERR_UNAUTHORIZED.
"""
from flask import request

from errors import err

KNOWN_ROLES = {"ContractAdmin", "Dispatcher", "Technician", "Customer"}


def authenticate():
    """Validate the two mandatory auth headers. Returns (user_id, role)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in KNOWN_ROLES:
        raise err("ERR_UNAUTHENTICATED", "Missing or unknown authentication headers")
    return user_id, role


def authorize(role, allowed_roles):
    """Role-authorization gate (priority 2). allowed_roles is an iterable."""
    if role not in allowed_roles:
        raise err("ERR_UNAUTHORIZED", "Role %s may not perform this operation" % role)
