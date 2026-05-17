"""Auth and RBAC helpers.

Every request (except the two test-driving operator utilities — clock advance
and sweep — per the PRD §2.1) must carry X-User-ID and X-User-Role headers.
"""
from functools import wraps
from typing import Iterable, Optional, Tuple

from flask import request

from app.errors import err_forbidden, err_unauthenticated


VALID_ROLES = {"PlatformAdmin", "ComplianceOfficer", "Physician", "Payer"}


def current_identity() -> Tuple[Optional[str], Optional[str]]:
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    return user_id, role


def require_auth() -> Tuple[str, str]:
    user_id, role = current_identity()
    if not user_id or not role:
        raise err_unauthenticated()
    if role not in VALID_ROLES:
        # An unknown role is "not authorized for this endpoint" → ERR_FORBIDDEN.
        raise err_forbidden()
    return user_id, role


def require_roles(allowed: Iterable[str]):
    """Decorator that enforces auth presence + role membership.

    Per validation priority (auth first, then authorization, then existence),
    we always raise ERR_UNAUTHENTICATED if headers are missing, before
    ERR_FORBIDDEN for a role that does not match.
    """
    allowed_set = set(allowed)

    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_id, role = require_auth()
            if role not in allowed_set:
                raise err_forbidden()
            return fn(*args, **kwargs)

        return wrapper

    return deco
