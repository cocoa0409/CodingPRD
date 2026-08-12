"""Auth middleware: X-User-ID / X-User-Role extraction and role gating."""

from flask import request

from errors import ApiError, ERR_UNAUTHENTICATED, ERR_UNAUTHORIZED

ROLES = ("Administrator", "Counselor", "Student")


def require_role(*allowed):
    """Validate auth headers and endpoint role permission.

    Returns (user_id, role). Raises 401 ERR_UNAUTHENTICATED when a header is
    missing or the role is unrecognized; 403 ERR_UNAUTHORIZED when the role is
    not permitted on this endpoint.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise ApiError(ERR_UNAUTHENTICATED, 401,
                       "Missing or unrecognized X-User-Role or missing X-User-ID")
    if allowed and role not in allowed:
        raise ApiError(ERR_UNAUTHORIZED, 403,
                       "Role %s is not permitted for this endpoint" % role)
    return user_id, role


def body():
    """JSON request body as a dict ({} when absent/non-object)."""
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}
