"""Authentication, role admission and per-request serialisation.

PRD 2.1: every request carries `X-User-ID` (acting principal) and `X-User-Role`
(the capacity in which it acts).
"""

import functools
import threading

from flask import request

import db
from errors import err

ROLE_UNDERWRITER = "UnderwritingOfficer"
ROLE_COMPLIANCE = "ComplianceOfficer"
ROLE_ADJUSTER = "ClaimsAdjuster"
ROLE_BUILDER = "BuilderPrincipal"
ROLE_HOMEOWNER = "Homeowner"

ALL_ROLES = (
    ROLE_UNDERWRITER,
    ROLE_COMPLIANCE,
    ROLE_ADJUSTER,
    ROLE_BUILDER,
    ROLE_HOMEOWNER,
)

CARRIER_ROLES = (ROLE_UNDERWRITER, ROLE_COMPLIANCE, ROLE_ADJUSTER)

_LOCK = threading.RLock()


def authenticate(allowed_roles):
    """Rungs 1 and 2 of PRD 2.8.  Returns (user_id, role)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or user_id.strip() == "" or role is None or role.strip() == "":
        raise err("ERR_UNAUTHENTICATED", "X-User-ID and X-User-Role headers are required")
    if role not in ALL_ROLES:
        raise err("ERR_ROLE_NOT_PERMITTED", "unknown role '%s'" % role)
    if role not in allowed_roles:
        raise err("ERR_ROLE_NOT_PERMITTED",
                  "role '%s' may not call this endpoint" % role)
    return user_id, role


def endpoint(*allowed_roles):
    """Wrap a view: serialise the request, authenticate, then flush the
    one-bump-per-row version bookkeeping when the handler succeeds."""

    def decorator(view):
        @functools.wraps(view)
        def wrapper(*args, **kwargs):
            with _LOCK:
                user_id, role = authenticate(allowed_roles)
                result = view(*args, user_id=user_id, role=role, **kwargs)
                db.flush_touches()
                return result

        return wrapper

    return decorator
