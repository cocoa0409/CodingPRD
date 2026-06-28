"""Auth header extraction and role checking.

Per PRD §2.1: every request must carry X-User-ID and X-User-Role. If either is
missing or malformed -> ERR_MISSING_AUTH_CONTEXT (401). If well-formed but the
role is not permitted for the operation -> ERR_FORBIDDEN_ROLE (403).
"""
from flask import request

from errors import err, ERR_MISSING_AUTH_CONTEXT, ERR_FORBIDDEN_ROLE

VALID_ROLES = {"PracticeAdmin", "FrontDesk", "Consultant", "BillingSpecialist", "Client"}


def get_auth():
    """Returns (user_id, role) or raises ERR_MISSING_AUTH_CONTEXT."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or role is None:
        raise err(ERR_MISSING_AUTH_CONTEXT, "Missing X-User-ID or X-User-Role header")
    if user_id.strip() == "" or role.strip() == "":
        raise err(ERR_MISSING_AUTH_CONTEXT, "Empty X-User-ID or X-User-Role header")
    if role not in VALID_ROLES:
        raise err(ERR_MISSING_AUTH_CONTEXT, "Malformed X-User-Role header")
    return user_id, role


def require_roles(role, allowed):
    """Raise ERR_FORBIDDEN_ROLE if role not in the allowed set."""
    if role not in allowed:
        raise err(ERR_FORBIDDEN_ROLE, "Role %s not permitted for this operation" % role)
