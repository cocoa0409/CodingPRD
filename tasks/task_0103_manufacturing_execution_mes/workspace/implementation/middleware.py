"""Auth header extraction, role checking, and request-body parsing helpers.

Auth headers (PRD §2.1): X-User-ID and X-User-Role. Both mandatory. The role
must be one of the five recognized roles, spelled exactly.
"""
from flask import request

import errors

KNOWN_ROLES = {
    "ManufacturingEngineer",
    "ProductionPlanner",
    "MachineOperator",
    "QualityInspector",
    "PlantAdmin",
}


def authenticate():
    """Validate the auth headers. Returns (user_id, role) or raises ApiError.

    Priority 1 (PRD §2.9 / validation #1): headers present and X-User-Role is a
    known role -> otherwise ERR_UNAUTHENTICATED (401).
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in KNOWN_ROLES:
        raise errors.unauthenticated()
    return user_id, role


def authorize(role, allowed_roles):
    """Priority 2 (PRD §2.9 / validation #2): acting role permitted for op.

    PlantAdmin is an operational override permitted everywhere. Any other role
    must appear in allowed_roles -> otherwise ERR_FORBIDDEN (403).
    """
    if role == "PlantAdmin":
        return
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
