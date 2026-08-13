"""Auth: X-User-ID / X-User-Role header extraction and role gating (PRD 2.1)."""
from functools import wraps

from flask import request

from errors import ApiError

ROLES = [
    "ProgramAdmin",
    "ConservationPlanner",
    "PaymentOfficer",
    "QualityAssuranceOfficer",
    "Applicant",
]
ANY_ROLE = tuple(ROLES)


def actor():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not isinstance(uid, str) or not role or role not in ROLES:
        raise ApiError(
            "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
            400,
            "X-User-ID and X-User-Role headers are required and X-User-Role must be a declared role",
        )
    return uid, role


def require_roles(*roles):
    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            uid, role = actor()
            if role not in roles:
                raise ApiError(
                    "ERR_UNAUTHORIZED_ROLE", 403,
                    f"Role {role} is not authorized for this endpoint",
                )
            kwargs["_uid"] = uid
            kwargs["_role"] = role
            return fn(*args, **kwargs)

        return wrapper

    return deco


def check_owner(applicant_id, uid):
    if applicant_id != uid:
        raise ApiError(
            "ERR_APPLICANT_NOT_OWNER", 403,
            "Applicant may only act on its own resources",
        )
