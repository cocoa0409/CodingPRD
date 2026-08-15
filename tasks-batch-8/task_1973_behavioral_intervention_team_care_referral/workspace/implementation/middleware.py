from flask import request

import errors as E
from db import store
from errors import ApiError

ALL_ROLES = (
    "Reporter",
    "CaseManager",
    "BITChair",
    "CounselingEvaluator",
    "DeanOfStudents",
    "PrivacyOfficer",
    "SystemAdmin",
)

ENTITY_BACKED_ROLES = tuple(r for r in ALL_ROLES if r != "SystemAdmin")


def require_auth(allowed_roles):
    """Validation ranks 1-2: request context, then role authorization.

    Returns (user_id, role).
    """
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ALL_ROLES:
        raise ApiError(
            E.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            400,
            "X-User-ID and X-User-Role headers are required and X-User-Role must be a declared role",
        )
    if role in ENTITY_BACKED_ROLES and uid not in store.staff:
        raise ApiError(
            E.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            400,
            "X-User-ID does not resolve to an existing staff record",
        )
    if role not in allowed_roles:
        raise ApiError(
            E.ERR_FORBIDDEN, 403, f"Role {role} is not authorized for this endpoint"
        )
    return uid, role
