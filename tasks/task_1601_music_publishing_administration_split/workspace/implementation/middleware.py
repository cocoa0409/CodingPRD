"""Auth context extraction and role checks (PRD section 2.1)."""
from flask import request

from errors import ApiError, ERR_AUTH, ERR_FORBIDDEN

ROLES = [
    "PublisherAdmin",
    "CopyrightSpecialist",
    "RoyaltyAnalyst",
    "FinanceManager",
    "Auditor",
    "Writer",
]
ALL_ROLES = list(ROLES)


def auth_context():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise ApiError(
            ERR_AUTH,
            400,
            "X-User-ID and X-User-Role headers must be present and "
            "X-User-Role must be a declared role",
        )
    return uid, role


def require_roles(role, allowed):
    if role not in allowed:
        raise ApiError(
            ERR_FORBIDDEN,
            403,
            "role %s is not permitted on this endpoint" % role,
        )
