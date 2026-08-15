"""Auth header extraction and role checking."""
from flask import request

from errors import unauthenticated, forbidden

VALID_ROLES = {"OpsAdmin", "ComplianceManager", "Trader", "Auditor"}


def get_identity():
    """Extract and validate X-User-ID / X-User-Role headers.

    Returns (user_id, role). Raises ERR_UNAUTHENTICATED when headers are
    missing or the role is unrecognized.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in VALID_ROLES:
        raise unauthenticated()
    return user_id, role


def require_roles(*roles):
    """Authenticate and require the caller's role to be one of `roles`."""
    user_id, role = get_identity()
    if role not in roles:
        raise forbidden()
    return user_id, role


def json_body():
    """Return the request JSON body as a dict (empty dict when absent)."""
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        from errors import invalid_request
        raise invalid_request("Request body must be a JSON object")
    return body
