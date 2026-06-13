"""Auth header extraction and role checking (PRD §2.1)."""
from functools import wraps

from flask import request, g

import errors

# The system recognizes exactly four roles (PRD §2.1).
VALID_ROLES = {"ShopManager", "BridalConsultant", "Seamstress", "FinanceClerk"}


def authenticate():
    """Validate the mandatory X-User-ID / X-User-Role headers (PRD §2.1)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not user_id.strip():
        errors.raise_error(errors.ERR_MISSING_USER_CONTEXT, "Missing X-User-ID header")
    if not role or role not in VALID_ROLES:
        errors.raise_error(
            errors.ERR_MISSING_USER_CONTEXT, "Missing or malformed X-User-Role header"
        )
    g.user_id = user_id
    g.role = role
    return role


def require_roles(*allowed):
    """Decorator: authenticate, then enforce role membership (priority 1 then 2)."""
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            role = authenticate()
            if role not in allowed:
                errors.raise_error(
                    errors.ERR_FORBIDDEN_ROLE,
                    "Role %s is not permitted for this operation" % role,
                )
            return fn(*args, **kwargs)

        return wrapper

    return decorator
