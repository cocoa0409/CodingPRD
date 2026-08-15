"""Auth header extraction and role checking per PRD §2.1 and §2.11 gates 1-2."""

from flask import request
import errors

# The five declared roles (PRD §2.1)
ROLES = {"OpsManager", "TourManager", "LogisticsCoordinator", "WarehouseTech", "PartnerVendorRep"}


def get_auth():
    """Gate 1: X-User-Role and X-User-ID headers present; role value declared."""
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if not role or not user_id:
        raise errors.unauthenticated("Missing X-User-Role or X-User-ID header")
    if role not in ROLES:
        raise errors.unauthenticated("Undeclared role value: %s" % role)
    return {"role": role, "user_id": user_id}


def require_roles(auth, allowed):
    """Gate 2: role permitted for this endpoint per RBAC matrix."""
    if auth["role"] not in allowed:
        raise errors.unauthorized("Role %s not permitted for this endpoint" % auth["role"])
