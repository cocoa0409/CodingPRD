"""Auth header extraction, role checking, pagination parsing."""
from functools import wraps
from flask import request, g

import errors as E


VALID_ROLES = {
    "ExecutiveProducer",
    "LineProducer",
    "FinanceController",
    "CastingDirector",
    "ProductionCoordinator",
}


def _check_auth():
    user_id = request.headers.get("X-User-ID", "")
    role = request.headers.get("X-User-Role", "")
    if not user_id or not user_id.strip() or not role or not role.strip():
        E.auth_required("Missing X-User-ID or X-User-Role")
    g.user_id = user_id.strip()
    g.role = role.strip()
    g.override_reason = (request.headers.get("X-Override-Reason", "") or "").strip()


def require_roles(*allowed_roles):
    """Decorator that:
    1. Enforces presence of X-User-ID + X-User-Role headers (ERR_AUTH_REQUIRED).
    2. Enforces that role is in allowed_roles (ERR_FORBIDDEN).
    Note: existence checks (route resource), pagination, body validation happen later.
    """
    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            _check_auth()
            if g.role not in allowed_roles:
                E.forbidden(f"Role {g.role} not authorized for this endpoint")
            return fn(*args, **kwargs)
        return wrapper
    return deco


def parse_pagination():
    """Parse and validate ?limit&offset from query string. Returns (limit, offset).

    Per scaffold: default limit=10, min=1, max=100, default offset=0, offset>=0.
    Out-of-bounds → ERR_INVALID_PAGINATION (HTTP 422).
    """
    raw_limit = request.args.get("limit", None)
    raw_offset = request.args.get("offset", None)
    try:
        limit = int(raw_limit) if raw_limit is not None else 10
    except (TypeError, ValueError):
        E.invalid_pagination("limit must be an integer")
    try:
        offset = int(raw_offset) if raw_offset is not None else 0
    except (TypeError, ValueError):
        E.invalid_pagination("offset must be an integer")
    if limit < 1 or limit > 100:
        E.invalid_pagination("limit out of bounds [1, 100]")
    if offset < 0:
        E.invalid_pagination("offset must be >= 0")
    return limit, offset
