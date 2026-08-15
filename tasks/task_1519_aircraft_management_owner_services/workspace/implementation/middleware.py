"""Auth context extraction and RBAC enforcement per PRD §2.1."""
from flask import request

from errors import missing_context, forbidden

ROLES = {
    "Owner",
    "AccountExecutive",
    "FlightOpsManager",
    "MaintenancePlanner",
    "FinanceController",
    "ComplianceOfficer",
    "ContractsManager",
    "PlatformAdmin",
}

# Roles permitted on plain read (GET) endpoints.
READ_ROLES = [
    "AccountExecutive", "Owner", "FlightOpsManager", "MaintenancePlanner",
    "FinanceController", "ComplianceOfficer", "ContractsManager",
]


def get_auth():
    """Extract and validate X-User-ID / X-User-Role. Returns (user_id, role)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise missing_context()
    return user_id, role


def require_roles(*allowed):
    user_id, role = get_auth()
    if role not in allowed:
        raise forbidden()
    return user_id, role


def require_read():
    return require_roles(*READ_ROLES)


def require_owner_of(user_id, role, owner_id):
    """Owner-scoped check: acting X-User-ID must equal the agreement's owner_id."""
    if role != "Owner" or user_id != owner_id:
        raise forbidden("Owner-scoped action attempted by a non-owner X-User-ID")
