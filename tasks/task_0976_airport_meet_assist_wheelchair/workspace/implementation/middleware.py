"""Auth middleware: X-User-ID / X-User-Role extraction + role checking."""
from flask import request

from errors import unauthenticated, unauthorized

ROLES = {
    "PlatformAdmin",
    "Requester",
    "Dispatcher",
    "Agent",
    "Confirmer",
    "OpsManager",
    "BillingClerk",
}


def get_auth():
    """Extract and validate auth headers. Returns (user_id, role). Raises 401."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not isinstance(user_id, str) or not user_id.strip():
        raise unauthenticated()
    if not role or role not in ROLES:
        raise unauthenticated()
    return user_id.strip(), role


def require_roles(*allowed):
    """Validate auth headers and role membership. Returns (user_id, role)."""
    user_id, role = get_auth()
    if role not in allowed:
        raise unauthorized()
    return user_id, role
