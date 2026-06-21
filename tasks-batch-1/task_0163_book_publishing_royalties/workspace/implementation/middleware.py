"""Auth header extraction and role validation (PRD §2.1 / §2.10)."""
from flask import request

import errors

ROLES = ("Publisher", "Author", "Agent")


def get_principal():
    """Validate the two required auth headers (priority 1).

    Returns (role, user_id) or raises ERR_UNAUTHENTICATED.
    """
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if not role or not user_id or role not in ROLES:
        raise errors.unauthenticated()
    return role, user_id


def require_publisher(role):
    """Priority 2: only Publisher may perform mutating/posting operations."""
    if role != "Publisher":
        raise errors.unauthorized()


def serialize(rec):
    """Strip internal-only fields (those prefixed with '_') from output."""
    return {k: v for k, v in rec.items() if not k.startswith("_")}
