"""PRD 2.1 auth: X-User-ID + X-User-Role headers, five fixed roles."""
from flask import request

from errors import ApiError

ROLES = ("RiskManager", "RiskOwner", "ControlOwner", "BoardReporter", "InternalAuditor")
ALL_ROLES = ROLES


def authenticate(allowed_roles):
    """Validation ladder priorities 1-2: authentication then role authorization."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", 401,
                       "X-User-ID and X-User-Role headers are required and the role must be recognized")
    if role not in allowed_roles:
        raise ApiError("ERR_FORBIDDEN", 403, "Role %s is not permitted on this endpoint" % role)
    return uid
