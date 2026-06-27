"""Auth header extraction and RBAC (PRD §2.1).

Every request carries X-User-ID and X-User-Role. Five roles are recognized,
spelled exactly: Petitioner, CourtExaminer, Judge, Fiduciary, CourtClerk.
"""

from flask import request

from errors import err

ROLES = {"Petitioner", "CourtExaminer", "Judge", "Fiduciary", "CourtClerk"}


def get_identity():
    """Validate auth headers (validation priority 1). Returns (user_id, role).

    Missing or malformed header -> ERR_UNAUTHENTICATED (401).
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or role is None:
        raise err("ERR_UNAUTHENTICATED", "Missing X-User-ID or X-User-Role header")
    if not isinstance(user_id, str) or user_id.strip() == "":
        raise err("ERR_UNAUTHENTICATED", "Malformed X-User-ID header")
    if role not in ROLES:
        raise err("ERR_UNAUTHENTICATED", "Malformed or unknown X-User-Role header")
    return user_id, role


def require_role(role, allowed):
    """RBAC check (validation priority 2). Acting role must be in `allowed`."""
    if role not in allowed:
        raise err("ERR_FORBIDDEN_ROLE", f"Role {role} may not invoke this operation")
