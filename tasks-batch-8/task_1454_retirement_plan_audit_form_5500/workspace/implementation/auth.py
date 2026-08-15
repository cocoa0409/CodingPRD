"""Auth middleware: X-User-ID / X-User-Role validation and per-endpoint RBAC."""
from functools import wraps

from flask import g, request

from errors import ERR_AUTH, ERR_FORBIDDEN, raise_err
from store import store

REAL_ROLES = {'SponsorAdmin', 'TPASpecialist', 'PlanAuditor', 'EngagementManager', 'System'}


def roles_allowed(*roles):
    """Decorator: validates auth headers (priority 1), then role membership (priority 2).

    Every wrapped view also runs inside the store lock and applies time-driven
    rules (extension expiry + posture re-evaluation) before handling.
    """
    from domain import apply_time_rules  # deferred to avoid circular import

    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            uid = request.headers.get('X-User-ID')
            role = request.headers.get('X-User-Role')
            if uid is None or not isinstance(uid, str) or not uid.strip():
                raise_err(ERR_AUTH, 'X-User-ID header missing or malformed')
            if role not in REAL_ROLES:
                raise_err(ERR_AUTH, 'X-User-Role header missing or malformed')
            if 'Any' not in roles and role not in roles:
                raise_err(ERR_FORBIDDEN, 'Role %s is not allowed to perform this operation' % role)
            g.user_id = uid
            g.user_role = role
            with store.lock:
                apply_time_rules()
                return fn(*args, **kwargs)
        return wrapper
    return deco
