"""Authentication and role-based access control (PRD 2.1, SCAFFOLD 1.7).

Every request must carry X-User-ID and X-User-Role. Recognized roles:
Owner, FarmManager, WholesaleBuyer, CrewLead. WholesaleBuyer identity is
entity-backed by BuyerAccount.id; CrewLead identity by Crew.id; Owner and
FarmManager identities are opaque operator identifiers.
"""
from flask import request

from errors import forbidden, unauthenticated

ROLES = ("Owner", "FarmManager", "WholesaleBuyer", "CrewLead")


def auth():
    """Extract and validate the auth headers. Returns (user_id, role)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not isinstance(user_id, str) or role not in ROLES:
        raise unauthenticated()
    return user_id, role


def require_role(*roles):
    """Authn + role permission. Returns (user_id, role).

    Role-permission failure raises ERR_FORBIDDEN (priority 2), which is
    evaluated immediately after authentication (priority 1).
    """
    user_id, role = auth()
    if role not in roles:
        raise forbidden()
    return user_id, role
