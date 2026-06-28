"""Auth header extraction and role checking (PRD §2.1, §2.6)."""
from flask import request

import errors

KNOWN_ROLES = {"AccountManager", "FieldSupervisor", "ClientContact", "PlatformAdmin"}


def get_identity():
    """Validate auth headers (priority 1). Returns (user_id, role)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in KNOWN_ROLES:
        raise errors.unauthenticated()
    return user_id, role


def require_role(role, allowed):
    """Role permission check (priority 2)."""
    if role not in allowed:
        raise errors.forbidden_role()
