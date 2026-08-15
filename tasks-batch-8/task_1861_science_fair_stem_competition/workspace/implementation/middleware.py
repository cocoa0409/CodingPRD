"""Auth header extraction and role checking.

Per PRD section 2.1: two mandatory headers X-User-ID and X-User-Role.
Declared roles: FairDirector, Mentor, EthicsReviewer, Judge,
OperationsLead, SafetyInspector.
"""

from flask import request
from errors import raise_err, ERR_UNAUTHENTICATED, ERR_UNAUTHORIZED

DECLARED_ROLES = {
    "FairDirector",
    "Mentor",
    "EthicsReviewer",
    "Judge",
    "OperationsLead",
    "SafetyInspector",
}

# Entity-backed roles: X-User-ID is the id of the acting entity
ENTITY_BACKED = {"Mentor", "Judge"}


def get_auth():
    """Return (user_id, role). Raises ERR_UNAUTHENTICATED when missing/invalid."""
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if not role or not user_id:
        raise_err(ERR_UNAUTHENTICATED,
                  "X-User-Role and X-User-ID headers are required")
    if role not in DECLARED_ROLES:
        raise_err(ERR_UNAUTHENTICATED, f"Undeclared role: {role}")
    return user_id, role


def require_roles(*allowed):
    """Authenticate and authorize. Returns (user_id, role)."""
    user_id, role = get_auth()
    if role not in allowed:
        raise_err(ERR_UNAUTHORIZED,
                  f"Role {role} is not permitted to invoke this endpoint")
    return user_id, role
