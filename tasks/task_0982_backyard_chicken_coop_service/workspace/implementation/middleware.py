"""Auth context extraction and role/ownership checks (PRD §2.1, §2.8)."""
from flask import request

from errors import fail

ROLES = {"Customer", "ServiceTech", "Dispatcher", "BillingAdmin", "PlatformAdmin"}

ALL_ROLES = ("Customer", "ServiceTech", "Dispatcher", "BillingAdmin", "PlatformAdmin")


def authenticate():
    """Priority 1: both headers present and role is a known role name."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        fail(
            "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
            "X-User-ID and X-User-Role headers are required and the role must be a known role",
        )
    return uid, role


def require_role(role, allowed):
    """Priority 2: caller role must be listed among the endpoint's roles."""
    if role not in allowed:
        fail("ERR_INSUFFICIENT_PERMISSIONS", f"Role {role} is not authorized for this operation")


def require_owner(uid, role, household_id):
    """Priority 3: household-scoped writes by a Customer require identity match."""
    if role == "Customer" and uid != household_id:
        fail("ERR_NOT_RESOURCE_OWNER", "Customer X-User-ID does not match the resource's household_id")


def require_tech(uid, technician_id):
    """Priority 3: technician-scoped actions require identity match."""
    if uid != technician_id:
        fail("ERR_NOT_ASSIGNED_TECH", "ServiceTech X-User-ID does not match the assigned technician")


def body():
    """Parse the JSON request body; absent body behaves as an empty object."""
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        fail("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    return data
