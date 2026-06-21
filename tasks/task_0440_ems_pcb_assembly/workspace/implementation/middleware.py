"""Auth header extraction and role checking.

PRD §2.1: every request carries X-User-ID and X-User-Role. The three known
roles are exactly ProcessEngineer, ProductionPlanner, QualityEngineer.
Missing header or unknown role -> ERR_UNAUTHENTICATED (401).
Known but unpermitted role -> ERR_FORBIDDEN (403).
X-User-ID is opaque and never compared to any entity id.
"""

from flask import request

import errors

KNOWN_ROLES = {"ProcessEngineer", "ProductionPlanner", "QualityEngineer"}


def authenticate():
    """Validate auth headers. Returns (user_id, role) or raises ApiError."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in KNOWN_ROLES:
        raise errors.unauthenticated()
    return user_id, role


def require_roles(role, allowed):
    """role must be in allowed set, else ERR_FORBIDDEN."""
    if role not in allowed:
        raise errors.forbidden()
