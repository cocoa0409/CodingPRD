"""Auth header extraction and RBAC (PRD §2.1, SCAFFOLD §1.4 auth, §1.7).

Every request must carry X-User-ID and X-User-Role. The recognized roles are
exactly Dispatcher, AccountHolder, CrewLead. Missing either header, or an
unrecognized role, -> ERR_UNAUTHENTICATED (401). A recognized role not
permitted for the endpoint -> ERR_FORBIDDEN (403).
"""
from flask import request

from errors import err

ROLES = {"Dispatcher", "AccountHolder", "CrewLead"}


def authenticate():
    """Return (user_id, role). Raise ERR_UNAUTHENTICATED if headers are bad."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role:
        raise err("ERR_UNAUTHENTICATED", "Missing X-User-ID or X-User-Role header.")
    if role not in ROLES:
        raise err("ERR_UNAUTHENTICATED", "Unrecognized X-User-Role.")
    return user_id, role


def authorize(role, allowed_roles):
    """Raise ERR_FORBIDDEN if role is not in the endpoint's allowed set."""
    if role not in allowed_roles:
        raise err("ERR_FORBIDDEN", "Role not permitted for this operation.")
