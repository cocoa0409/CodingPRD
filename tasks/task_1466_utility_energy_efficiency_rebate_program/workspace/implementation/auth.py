"""Auth header extraction and role checking (PRD section 2.1)."""
from functools import wraps

from flask import g, request

from errors import ApiError

ROLES = (
    "ProgramAdministrator",
    "TradeAlly",
    "VerificationInspector",
    "PaymentProcessor",
    "RegulatorAnalyst",
)

ALL_ROLES = ROLES


def require_roles(*allowed):
    def deco(fn):
        @wraps(fn)
        def inner(*args, **kwargs):
            uid = request.headers.get("X-User-ID")
            role = request.headers.get("X-User-Role")
            if uid is None or not uid.strip() or role not in ROLES:
                raise ApiError(
                    "ERR_UNAUTHENTICATED",
                    401,
                    "Missing or malformed X-User-ID / X-User-Role headers",
                )
            if role not in allowed:
                raise ApiError(
                    "ERR_UNAUTHORIZED",
                    403,
                    "Role %s is not authorized for this endpoint" % role,
                )
            g.user_id = uid
            g.user_role = role
            return fn(*args, **kwargs)

        return inner

    return deco
