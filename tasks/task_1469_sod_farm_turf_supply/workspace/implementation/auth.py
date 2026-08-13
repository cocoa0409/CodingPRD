"""Authentication / authorization middleware per PRD section 2.1."""
from flask import request

from errors import err, ERR_UNAUTHENTICATED, ERR_UNAUTHORIZED_ROLE

ROLES = {"FarmManager", "SalesRep", "HarvestSupervisor", "FleetManager", "Customer"}


def authenticate():
    """Tier 1: both headers present and the role is declared."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise err(ERR_UNAUTHENTICATED, "missing or invalid X-User-ID / X-User-Role headers")
    return user_id, role


def require_roles(*allowed):
    """Tier 2 (role half): the role is permitted on the endpoint."""
    user_id, role = authenticate()
    if role not in allowed:
        raise err(ERR_UNAUTHORIZED_ROLE, f"role {role} is not permitted for this operation")
    return user_id, role


def check_ownership(user_id, role, customer_id):
    """Tier 2 (ownership half): Customer may act only on their own resources."""
    if role == "Customer" and user_id != customer_id:
        raise err(ERR_UNAUTHORIZED_ROLE, "customers may only access their own resources")
