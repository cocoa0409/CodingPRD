from flask import request

from errors import ApiError

ROLES = {"PbmAdmin", "Pharmacist", "Member", "ClinicalReviewer", "Auditor"}


def get_auth():
    """Pipeline stage 1: headers present and role recognized."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise ApiError(
            "ERR_UNAUTHENTICATED",
            "X-User-ID and X-User-Role headers are required and the role must be recognized",
            401,
        )
    return uid, role


def require_roles(*roles):
    """Pipeline stages 1-2: authentication, then role authorization."""
    uid, role = get_auth()
    if role not in roles:
        raise ApiError(
            "ERR_FORBIDDEN_ROLE",
            f"Role {role} is not authorized for this endpoint",
            403,
        )
    return uid, role
