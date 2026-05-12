"""Auth and RBAC middleware per PRD §2.1."""

from flask import request, g
from errors import (
    AppError,
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
    ERR_FORBIDDEN_FOR_ROLE,
)

VALID_ROLES = {
    "Applicant",
    "Beneficiary",
    "IssuingBank",
    "AdvisingBank",
    "ConfirmingBank",
    "NegotiatingBank",
    "Operator",
    "Auditor",
}


def require_auth():
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in VALID_ROLES:
        raise AppError(
            ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            "Missing or invalid X-User-ID/X-User-Role header.",
            400,
        )
    g.user_id = user_id
    g.role = role


def require_role(*allowed_roles):
    if g.role not in allowed_roles:
        raise AppError(ERR_FORBIDDEN_FOR_ROLE, f"Role {g.role} forbidden for this endpoint.", 403)
