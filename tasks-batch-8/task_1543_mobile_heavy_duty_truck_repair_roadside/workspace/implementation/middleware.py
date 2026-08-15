"""Auth header extraction and role checking (PRD 2.1)."""
from flask import request

from errors import err_unauthenticated, err_unauthorized_role, err_forbidden_ownership

ROLES = {
    "OpsAdmin", "Dispatcher", "Technician", "FleetManager",
    "BillingClerk", "WarrantyAdministrator", "SafetyOfficer",
}


def auth(required_roles):
    """Validate X-User-ID / X-User-Role and endpoint role membership.

    Returns (user_id, role).
    """
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if uid is None or not uid.strip() or role is None or not role.strip():
        raise err_unauthenticated()
    if role not in required_roles:
        raise err_unauthorized_role()
    return uid, role


def require_technician_self(user_id, technician_id):
    if user_id != technician_id:
        raise err_forbidden_ownership(
            "Technician may act only on their own dispatches / work")


def require_fleet_ownership(user_id, fleet_account_id):
    if fleet_account_id is None or user_id != fleet_account_id:
        raise err_forbidden_ownership(
            "FleetManager may act only on their own fleet's resources")
