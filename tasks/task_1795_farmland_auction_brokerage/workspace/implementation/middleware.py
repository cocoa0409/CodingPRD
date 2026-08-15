"""Authentication and authorization helpers.

Auth contract (PRD 2.1): every request carries X-User-ID and X-User-Role.
Roles: Seller, BrokerAgent, Buyer, PlatformAdmin.
"""

from flask import request

from errors import raise_err, ERR_UNAUTHENTICATED, ERR_FORBIDDEN

ROLES = {"Seller", "BrokerAgent", "Buyer", "PlatformAdmin"}


def auth():
    """Validate auth headers. Returns (user_id, role)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise_err(ERR_UNAUTHENTICATED, "missing or unrecognized X-User-ID / X-User-Role")
    return user_id, role


def require_roles(role, allowed):
    if role not in allowed:
        raise_err(ERR_FORBIDDEN, f"role {role} is not permitted for this operation")


def forbid(msg="ownership check failed"):
    raise_err(ERR_FORBIDDEN, msg)
