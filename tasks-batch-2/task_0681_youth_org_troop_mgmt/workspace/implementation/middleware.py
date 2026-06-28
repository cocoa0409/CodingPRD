"""Authentication and role-based access control (PRD §2.1).

Every request must carry X-User-ID and X-User-Role. The two recognized roles are
spelled exactly CouncilRegistrar and TroopLeader. Missing headers or an unknown
role -> ERR_UNAUTHENTICATED. A well-formed but unauthorized role for the
operation -> ERR_FORBIDDEN_ROLE.
"""
from flask import request

from errors import err, ERR_UNAUTHENTICATED, ERR_FORBIDDEN_ROLE

ROLE_COUNCIL_REGISTRAR = "CouncilRegistrar"
ROLE_TROOP_LEADER = "TroopLeader"
KNOWN_ROLES = {ROLE_COUNCIL_REGISTRAR, ROLE_TROOP_LEADER}


def authenticate():
    """Validate headers; returns (user_id, role). Raises ERR_UNAUTHENTICATED."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in KNOWN_ROLES:
        raise err(ERR_UNAUTHENTICATED, "missing or invalid authentication headers")
    return user_id, role


def require_roles(role, allowed_roles):
    """Raise ERR_FORBIDDEN_ROLE unless role is in allowed_roles."""
    if role not in allowed_roles:
        raise err(ERR_FORBIDDEN_ROLE, "role not permitted for this operation")


# Convenience constants for endpoint decorators.
BOTH_ROLES = (ROLE_COUNCIL_REGISTRAR, ROLE_TROOP_LEADER)
REGISTRAR_ONLY = (ROLE_COUNCIL_REGISTRAR,)
LEADER_ONLY = (ROLE_TROOP_LEADER,)
