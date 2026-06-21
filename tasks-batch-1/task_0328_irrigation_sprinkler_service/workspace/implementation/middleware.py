"""Auth header extraction and role checks (PRD §2.1).

Headers: X-User-ID, X-User-Role.
Roles (spelled precisely): Dispatcher, Technician, Customer, BackflowTester.
"""
from flask import request

import errors
from errors import fail

VALID_ROLES = {"Dispatcher", "Technician", "Customer", "BackflowTester"}


def get_auth():
    """Return (user_id, role). Raises ERR_MISSING_USER_CONTEXT (401) if either
    header is missing/blank or the role is not one of the four recognized roles."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or role is None:
        fail(errors.ERR_MISSING_USER_CONTEXT, "Missing X-User-ID or X-User-Role header")
    user_id = user_id.strip()
    role = role.strip()
    if not user_id or not role:
        fail(errors.ERR_MISSING_USER_CONTEXT, "Blank X-User-ID or X-User-Role header")
    if role not in VALID_ROLES:
        fail(errors.ERR_MISSING_USER_CONTEXT, "Unrecognized role: %s" % role)
    return user_id, role


def require_role(role, allowed):
    """Priority-2 role check. Raises ERR_FORBIDDEN_ROLE (403) when the acting
    role is not in the allowed set for this operation."""
    if role not in allowed:
        fail(errors.ERR_FORBIDDEN_ROLE, "Role %s not permitted for this operation" % role)
