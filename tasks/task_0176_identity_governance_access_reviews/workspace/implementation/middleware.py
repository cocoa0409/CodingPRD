"""Auth header extraction, role checking, and request-body helpers.

Auth headers (PRD §2.1): X-User-ID and X-User-Role, both mandatory.
Recognized roles: CatalogAdmin, AccessManager, AccessApprover, CampaignAdmin,
Certifier.
"""
from flask import request

import errors
from errors import err

RECOGNIZED_ROLES = {
    "CatalogAdmin",
    "AccessManager",
    "AccessApprover",
    "CampaignAdmin",
    "Certifier",
}


def get_identity():
    """Returns (user_id, role). Raises ERR_UNAUTHENTICATED when either header
    is missing (PRD §2.1, validation priority 1)."""
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if not user_id or not role:
        raise err(errors.ERR_UNAUTHENTICATED,
                  "Both X-User-ID and X-User-Role headers are required")
    return user_id, role


def require_role(allowed_roles):
    """Authenticate then authorize. Returns (user_id, role).

    Priority 1: ERR_UNAUTHENTICATED (missing header).
    Priority 2: ERR_FORBIDDEN_ROLE (role not permitted for this op).

    A role value outside the recognized five is treated as not permitted
    (ERR_FORBIDDEN_ROLE) once the headers are present.
    """
    user_id, role = get_identity()
    if role not in allowed_roles:
        raise err(errors.ERR_FORBIDDEN_ROLE,
                  "Role %s is not permitted for this operation" % role)
    return user_id, role


def get_json_body():
    """Parse the request body as JSON. A non-JSON / unparseable body for a
    write endpoint is treated as a malformed request (ERR_VALIDATION)."""
    if request.method in ("POST", "PATCH", "PUT"):
        data = request.get_json(silent=True)
        if data is None:
            # Empty body is acceptable for transition endpoints that take no
            # input; represent it as an empty object so callers can read keys.
            if request.data and request.data.strip():
                raise err(errors.ERR_VALIDATION, "Malformed JSON body")
            return {}
        if not isinstance(data, dict):
            raise err(errors.ERR_VALIDATION, "Body must be a JSON object")
        return data
    return {}
