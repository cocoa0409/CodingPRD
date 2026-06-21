"""Auth header extraction and role checking (PRD §2.1, §2.10)."""
from flask import request

from errors import err

VALID_ROLES = {"BrokerageAdmin", "ListingBroker", "TenantBroker"}


def authenticate():
    """Validate the two mandatory headers. Returns (user_id, role).

    Raises ERR_UNAUTHENTICATED if either header is missing or the role is
    not one of the declared roles (PRD §2.1).
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in VALID_ROLES:
        raise err("ERR_UNAUTHENTICATED", "Missing or invalid authentication headers")
    return user_id, role


def require_role(role, allowed):
    """Role-authorization gate (PRD §2.10 — ERR_FORBIDDEN_ROLE)."""
    if role not in allowed:
        raise err("ERR_FORBIDDEN_ROLE", "Role not permitted for this operation")
