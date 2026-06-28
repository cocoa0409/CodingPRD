"""Authentication + RBAC (PRD §2.1, §2.11 priorities 1-2).

Every request must carry X-User-ID (acting operator) and X-User-Role (role).
The system recognizes exactly two roles spelled precisely: Teller and
StoreManager. A missing or unrecognized header yields ERR_UNAUTHENTICATED; a
recognized role not permitted for the operation yields ERR_FORBIDDEN_ROLE.

Both roles use an opaque identity — X-User-ID is never matched against any
persisted entity id; it is only recorded (creating Teller) and compared
operator-to-operator for segregation of duties."""
from flask import request

import errors

TELLER = "Teller"
STORE_MANAGER = "StoreManager"

KNOWN_ROLES = {TELLER, STORE_MANAGER}

BOTH = [TELLER, STORE_MANAGER]
MANAGER_ONLY = [STORE_MANAGER]


class Caller:
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role


def require_auth(allowed_roles):
    """Run auth (priority 1) then RBAC (priority 2), returning the Caller.

    PRD §2.1: missing/invalid X-User-ID or X-User-Role -> ERR_UNAUTHENTICATED;
    recognized role not permitted -> ERR_FORBIDDEN_ROLE."""
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if not role or role not in KNOWN_ROLES or not user_id:
        raise errors.err(errors.ERR_UNAUTHENTICATED, "Missing or invalid auth headers")
    if role not in allowed_roles:
        raise errors.err(errors.ERR_FORBIDDEN_ROLE, "Role not permitted for this operation")
    return Caller(user_id, role)
