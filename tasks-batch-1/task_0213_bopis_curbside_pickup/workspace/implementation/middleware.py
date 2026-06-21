"""Auth header extraction, RBAC, and shared request helpers.

Auth scheme (PRD §2.1): every protected endpoint requires X-User-ID and
X-User-Role. Six roles spelled exactly: Anonymous, Customer, StorePicker,
StoreAssociate, StoreManager, PlatformAdmin. Customer is entity-backed
(X-User-ID == acting Customer.id); the rest are opaque.
"""

from flask import request

from errors import err

ROLES = {
    "Anonymous", "Customer", "StorePicker",
    "StoreAssociate", "StoreManager", "PlatformAdmin",
}


def get_identity():
    """Return (user_id, role). Raises ERR_UNAUTHENTICATED when either is missing."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role:
        raise err("ERR_UNAUTHENTICATED",
                  "X-User-ID and X-User-Role headers are required")
    return user_id, role


def require_auth(allowed_roles):
    """Auth (priority 1) then role authorization (priority 2).

    Returns (user_id, role). Raises ERR_UNAUTHENTICATED / ERR_UNAUTHORIZED.
    """
    user_id, role = get_identity()
    if role not in allowed_roles:
        raise err("ERR_UNAUTHORIZED",
                  "role %s is not permitted for this endpoint" % role)
    return user_id, role


def get_json_body():
    """Parse the JSON body, tolerating empty bodies (returns {})."""
    if request.content_length in (None, 0):
        return {}
    data = request.get_json(silent=True)
    if data is None:
        # body present but not valid JSON
        if request.get_data(cache=True):
            raise err("ERR_INVALID_REQUEST", "request body must be valid JSON")
        return {}
    if not isinstance(data, dict):
        raise err("ERR_INVALID_REQUEST", "request body must be a JSON object")
    return data
