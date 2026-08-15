"""Auth header extraction and role checking (PRD section 2.1)."""
from flask import g, request

from errors import ERR_FORBIDDEN, ERR_UNAUTHENTICATED, raise_err

ROLES = {"RanchManager", "RangeHand", "WoolPoolOperator", "GrazingClient", "PlatformAdmin"}


def authenticate():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not isinstance(uid, str):
        raise_err(ERR_UNAUTHENTICATED, "missing X-User-ID header")
    if not role or role not in ROLES:
        raise_err(ERR_UNAUTHENTICATED, "missing or unknown X-User-Role header")
    g.user_id = uid
    g.user_role = role


def require_roles(*roles):
    authenticate()
    if g.user_role not in roles:
        raise_err(ERR_FORBIDDEN, "role %s is not permitted on this endpoint" % g.user_role)


def before_request_auth():
    """Layer-1 authentication for every /api route, including unknown paths."""
    if request.path.startswith("/api"):
        authenticate()
