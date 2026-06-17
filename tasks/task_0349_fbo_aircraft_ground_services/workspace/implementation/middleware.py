"""Auth header extraction and role checking (PRD §2.1, §3.10)."""
from flask import request

import errors
from errors import err

KNOWN_ROLES = {"OpsDispatcher", "FuelTech", "BillingClerk", "LineManager", "Operator"}


def authenticate():
    """PRD §2.1: both X-User-ID and X-User-Role must be present, and the role
    must be one the system recognizes. Otherwise ERR_UNAUTHENTICATED (401)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in KNOWN_ROLES:
        raise err(errors.ERR_UNAUTHENTICATED, "Missing or unknown authentication headers.")
    return user_id, role


def require_role(role, allowed_roles):
    """PRD §2.1: caller role must be authorized for this operation, else
    ERR_FORBIDDEN_ROLE (403)."""
    if role not in allowed_roles:
        raise err(errors.ERR_FORBIDDEN_ROLE, "Role not permitted for this operation.")
