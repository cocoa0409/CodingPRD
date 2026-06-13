"""Authentication / role extraction.

Per PRD §2.1: every request carries X-User-ID and X-User-Role. The three valid
roles are spelled exactly Landlord, Tenant, EscrowAgent. A missing or unknown
role yields ERR_UNAUTHENTICATED (401). Permission + ownership failures yield
ERR_FORBIDDEN (403), enforced by the routes.
"""

from flask import request

from errors import err

VALID_ROLES = {"Landlord", "Tenant", "EscrowAgent"}


def get_auth():
    """Return (user_id, role). Raises ERR_UNAUTHENTICATED if role invalid.

    Auth (role presence/validity) is the highest-precedence check (PRD §2.8).
    """
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if role is None or role not in VALID_ROLES:
        raise err("ERR_UNAUTHENTICATED", "Missing or unknown X-User-Role header")
    return user_id, role


def require_role(role, allowed):
    """Authorization tier (PRD §2.8 step 2). Role must be in allowed set."""
    if role not in allowed:
        raise err("ERR_FORBIDDEN", "Role not permitted for this operation")
