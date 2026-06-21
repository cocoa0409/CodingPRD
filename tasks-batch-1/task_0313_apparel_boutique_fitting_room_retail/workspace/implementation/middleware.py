"""Auth (header extraction), RBAC enforcement, and request-parsing helpers."""
from flask import request

import errors
from errors import err

KNOWN_ROLES = {"Customer", "StoreAssociate", "Merchandiser", "StoreManager"}


def authenticate():
    """PRD §2.1: X-User-ID and X-User-Role both required; role must be known.

    Returns (user_id, role). Raises ERR_UNAUTHENTICATED on any failure.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in KNOWN_ROLES:
        raise err(errors.ERR_UNAUTHENTICATED, "Missing or invalid authentication headers")
    return user_id, role


def require_role(role, allowed):
    """PRD §2.1: ERR_FORBIDDEN_ROLE when the acting role is not permitted."""
    if role not in allowed:
        raise err(errors.ERR_FORBIDDEN_ROLE, "Role not permitted for this operation")


def get_json_body():
    """Parse the JSON body; tolerate empty/missing body as {}."""
    if not request.data:
        return {}
    data = request.get_json(silent=True)
    if data is None:
        # Body present but not valid JSON.
        raise err(errors.ERR_INVALID_REQUEST, "Request body is not valid JSON")
    if not isinstance(data, dict):
        raise err(errors.ERR_INVALID_REQUEST, "Request body must be a JSON object")
    return data
