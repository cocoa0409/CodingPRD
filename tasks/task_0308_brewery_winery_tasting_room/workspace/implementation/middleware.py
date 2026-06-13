"""Auth header extraction and RBAC enforcement (PRD §2.1, §2.9)."""
from flask import request

from errors import err, ERR_UNAUTHENTICATED, ERR_FORBIDDEN
from constants import ROLES


def authenticate():
    """Validate the two mandatory auth headers (PRD §2.1).

    X-User-ID identifies the acting user; X-User-Role declares the operational
    capacity. Missing or malformed -> ERR_UNAUTHENTICATED (401).

    Returns (user_id, role).
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not isinstance(user_id, str) or not user_id.strip():
        raise err(ERR_UNAUTHENTICATED, "Missing or malformed X-User-ID header")
    if not role or role not in ROLES:
        raise err(ERR_UNAUTHENTICATED, "Missing or malformed X-User-Role header")
    return user_id, role


def authorize(role, allowed_roles):
    """Role authorization per the §4 matrix (PRD §2.1, §2.9).

    Well-formed but not-permitted role -> ERR_FORBIDDEN (403).
    """
    if role not in allowed_roles:
        raise err(ERR_FORBIDDEN, f"Role {role} is not permitted for this operation")
