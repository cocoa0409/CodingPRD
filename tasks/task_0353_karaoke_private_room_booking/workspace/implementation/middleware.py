"""Auth header extraction and RBAC (PRD §2.1, §2.8).

Two mandatory headers on every request:
  X-User-ID   — acting user id (for Customer, equals their Customer.id)
  X-User-Role — one of VenueManager | FrontDesk | Customer

Missing/unknown -> ERR_UNAUTHENTICATED (401).
Role not permitted / Customer not owning -> ERR_FORBIDDEN (403).
"""

from flask import request

import errors

KNOWN_ROLES = {"VenueManager", "FrontDesk", "Customer"}


def get_identity():
    """Return (user_id, role). Raise ERR_UNAUTHENTICATED if invalid (PRD §2.1)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in KNOWN_ROLES:
        raise errors.unauthenticated()
    return user_id, role


def require_role(role, allowed):
    """Authorization gate (PRD §2.8 priority 2). allowed is a set of role names."""
    if role not in allowed:
        raise errors.forbidden()
