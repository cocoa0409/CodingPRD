"""Auth + RBAC (PRD §2.1, §3.9).

Two mandatory headers: X-User-ID and X-User-Role. The six recognized roles are
spelled precisely as: DealerAdmin, SalesRep, FinanceManager, ServiceAdvisor,
PartsClerk, AuctionClerk. Identity is opaque (never matched to entity ids).
"""
from functools import wraps

from flask import request

import errors
from errors import err

KNOWN_ROLES = {
    "DealerAdmin",
    "SalesRep",
    "FinanceManager",
    "ServiceAdvisor",
    "PartsClerk",
    "AuctionClerk",
}


def authenticate():
    """Validate the two mandatory headers. Returns (user_id, role) or raises."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in KNOWN_ROLES:
        raise err(errors.ERR_UNAUTHENTICATED, "Missing or invalid authentication headers.")
    return user_id, role


def require_roles(*allowed):
    """Decorator: authenticate first (ERR_UNAUTHENTICATED), then enforce role
    membership (ERR_FORBIDDEN). Auth precedes authorization per §3.9."""
    allowed_set = set(allowed)

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            _user_id, role = authenticate()
            if role not in allowed_set:
                raise err(errors.ERR_FORBIDDEN, "Role not permitted for this operation.")
            return fn(*args, **kwargs)

        return wrapper

    return decorator
