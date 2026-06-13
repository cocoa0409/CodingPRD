"""Auth & RBAC (PRD §2.1, SCAFFOLD §1.7).

Headers: X-User-ID (acting principal) and X-User-Role (operational capacity).
Roles: CarrierAgent, Subscriber, PortingOps, BillingSystem.
"""
from flask import request

from errors import err, ERR_UNAUTHENTICATED, ERR_FORBIDDEN

KNOWN_ROLES = {"CarrierAgent", "Subscriber", "PortingOps", "BillingSystem"}


def authenticate():
    """Validate both headers exist and the role is recognized.

    Runs before any other validation (PRD §2.1). Returns (user_id, role).
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in KNOWN_ROLES:
        err(ERR_UNAUTHENTICATED, "missing or invalid X-User-ID / X-User-Role")
    return user_id, role


def authorize(role, allowed_roles):
    """Confirm the acting role is permitted for the endpoint (PRD §2.1)."""
    if role not in allowed_roles:
        err(ERR_FORBIDDEN, f"role {role} not permitted for this operation")
