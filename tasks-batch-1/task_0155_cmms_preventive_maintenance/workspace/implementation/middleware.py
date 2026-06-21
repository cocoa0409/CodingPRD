"""Auth header extraction, role checking, and request-body parsing helpers.

Auth headers (PRD §2.1): X-User-ID identifies the acting user, X-User-Role
declares the role. Both are required. The role must be one of exactly five
recognized roles, spelled precisely:
    MaintenanceManager, Planner, Technician, InventoryClerk, WarrantyAdmin
"""
from flask import request

import errors

KNOWN_ROLES = {
    "MaintenanceManager",
    "Planner",
    "Technician",
    "InventoryClerk",
    "WarrantyAdmin",
}


def authenticate():
    """Validate auth headers (validation priority 1, PRD §2.1/§3.10).

    A missing or unrecognized X-User-Role yields ERR_UNAUTHENTICATED (401).
    X-User-ID must also be present (it identifies the acting user; for a
    Technician it is the acting Technician.id used in ownership checks).
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not role or role not in KNOWN_ROLES:
        raise errors.unauthenticated()
    if not user_id:
        raise errors.unauthenticated("Missing X-User-ID header.")
    return user_id, role


def authorize(role, allowed_roles):
    """Validation priority 2 (PRD §3.10): acting role permitted for the op.

    A recognized role lacking permission yields ERR_FORBIDDEN (403). There is
    no blanket override: MaintenanceManager is permitted only where it is
    explicitly listed among the authorized roles (PRD §4 endpoint table).
    """
    if role not in allowed_roles:
        raise errors.forbidden()


def get_json_body():
    """Parse the JSON request body. Returns {} when absent.

    A body that is present but not a JSON object is a malformed request.
    """
    if request.method in ("GET", "DELETE"):
        return {}
    raw = request.get_data(cache=True)
    if not raw:
        return {}
    try:
        body = request.get_json(force=True, silent=False)
    except Exception:
        raise errors.invalid_request("Request body is not valid JSON.")
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise errors.invalid_request("Request body must be a JSON object.")
    return body
