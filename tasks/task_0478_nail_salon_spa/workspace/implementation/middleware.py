"""Auth header extraction and RBAC enforcement (PRD §2.1).

Every request must carry X-User-ID and X-User-Role. The four recognized roles:
SalonManager, FrontDesk, Technician, Client. SalonManager and FrontDesk are
opaque (never ownership-checked); Technician and Client are entity-backed and
subject to ownership comparison against X-User-ID.
"""
from flask import request

from errors import err, ERR_UNAUTHENTICATED, ERR_FORBIDDEN

VALID_ROLES = {"SalonManager", "FrontDesk", "Technician", "Client"}
ENTITY_BACKED = {"Technician", "Client"}


def get_auth():
    """Return (user_id, role). Raise ERR_UNAUTHENTICATED if headers missing or
    X-User-Role is not a recognized role (PRD §2.1, priority 1)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in VALID_ROLES:
        raise err(ERR_UNAUTHENTICATED, "Missing or invalid authentication headers")
    return user_id, role


def authorize(allowed_roles):
    """Authenticate then check role permission (PRD §2.11 priority 1 then 2).

    Returns (user_id, role). Raises ERR_UNAUTHENTICATED (401) or ERR_FORBIDDEN (403).
    Ownership (also ERR_FORBIDDEN) is enforced separately by callers once the
    owning FK is known, since existence (404) is checked before ownership in
    transition flows; per §2.11 ownership is part of the priority-2 auth check.
    """
    user_id, role = get_auth()
    if role not in allowed_roles:
        raise err(ERR_FORBIDDEN, f"Role {role} is not permitted for this operation")
    return user_id, role
