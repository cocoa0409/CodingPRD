from flask import request
from errors import err_missing_headers, err_insufficient

VALID_ROLES = {
    "ShopAdmin",
    "ServiceManager",
    "Technician",
    "WindingTechnician",
    "Estimator",
    "Customer",
}


def get_auth():
    """Extract and validate user context headers. Returns (user_id, role)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role:
        raise err_missing_headers()
    if role not in VALID_ROLES:
        raise err_missing_headers()
    return user_id, role


def require_role(*allowed):
    user_id, role = get_auth()
    if role not in allowed:
        raise err_insufficient()
    return user_id, role
