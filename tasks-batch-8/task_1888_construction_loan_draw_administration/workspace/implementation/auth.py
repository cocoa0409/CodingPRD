"""Auth context, role authorization, and borrower ownership per PRD §2.1."""

from flask import request

from errors import ApiError

ROLES = {
    "LenderAdmin",
    "DrawProcessor",
    "CreditOfficer",
    "LoanServicer",
    "Inspector",
    "Borrower",
}

ALL_ROLES = frozenset(ROLES)


def auth_context():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise ApiError(
            "ERR_MISSING_OR_INVALID_USER_CONTEXT",
            "Missing or invalid X-User-ID / X-User-Role headers",
        )
    return uid, role


def require_role(role, allowed):
    if role not in allowed:
        raise ApiError(
            "ERR_FORBIDDEN_FOR_ROLE",
            f"Role {role} is not permitted for this endpoint",
        )


def require_borrower_ownership(uid, loan):
    if loan["borrower_id"] != uid:
        raise ApiError(
            "ERR_FORBIDDEN_FOR_ROLE",
            "Borrower may only perform writes against its own loans",
        )
