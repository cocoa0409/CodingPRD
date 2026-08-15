"""Auth header extraction and role checking (PRD §2.1, §2.8).

Every request carries X-User-ID and X-User-Role. Missing or malformed
headers -> ERR_UNAUTHENTICATED (401). A role not permitted to invoke the
endpoint -> ERR_UNAUTHORIZED (403).
"""

from flask import request

import db
from errors import unauthenticated, unauthorized

VALID_ROLES = ("Producer", "CountySpecialist", "CountyExecutiveDirector", "CountyCommittee")

# Roles whose X-User-ID is entity-backed (must resolve to a Producer id).
ENTITY_BACKED_ROLES = ("Producer", "CountyCommittee")

ALL_ROLES = list(VALID_ROLES)


def current_auth():
    """Return (user_id, role) after validating headers (validation priority 1)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not isinstance(user_id, str) or not user_id.strip():
        raise unauthenticated()
    if not role or role not in VALID_ROLES:
        raise unauthenticated()
    return user_id.strip(), role


def require_roles(allowed):
    """Validate auth headers then enforce role membership (priorities 1-2)."""
    user_id, role = current_auth()
    if role not in allowed:
        raise unauthorized()
    return user_id, role


def resolve_entity_backed_caller(user_id, role):
    """For entity-backed roles, the X-User-ID must resolve to a Producer
    (existence validation, priority 3). Returns the Producer or None for
    opaque roles."""
    if role in ENTITY_BACKED_ROLES:
        return db.producers.get(user_id)
    return None
