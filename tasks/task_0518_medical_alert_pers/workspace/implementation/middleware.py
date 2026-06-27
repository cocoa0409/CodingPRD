"""Auth header extraction and RBAC (PRD 2.1, 2.9, SCAFFOLD 1.4 priorities 1-2).

Auth headers (PRD 2.1):
  X-User-ID   — acting user id
  X-User-Role — one of PlatformAdmin, Subscriber, CallCenterAgent

Order: ERR_UNAUTHENTICATED (401) before ERR_FORBIDDEN (403).
"""
from flask import request

from errors import err

VALID_ROLES = {"PlatformAdmin", "Subscriber", "CallCenterAgent"}


def get_auth():
    """Return (user_id, role). Raise ERR_UNAUTHENTICATED when missing/malformed.

    PRD 2.1: every request must carry X-User-ID and X-User-Role; missing or malformed
    -> ERR_UNAUTHENTICATED. The clock endpoint is no exception.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role:
        raise err("ERR_UNAUTHENTICATED", "Missing X-User-ID or X-User-Role header")
    if role not in VALID_ROLES:
        raise err("ERR_UNAUTHENTICATED", "Malformed X-User-Role header")
    return user_id, role


def require_role(role, allowed):
    """RBAC check (priority 2). Raise ERR_FORBIDDEN if role not in allowed set."""
    if role not in allowed:
        raise err("ERR_FORBIDDEN", "Role %s not permitted for this operation" % role)
