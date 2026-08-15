"""Auth header extraction and role checks (PRD 2.1, validation priorities 1-2)."""
from flask import request

from errors import (
    raise_error,
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
    ERR_FORBIDDEN_FOR_ROLE,
)

ALL_ROLES = {"FilmOfficeAdmin", "FilmOfficeReviewer", "Producer", "CPAAuditor", "CreditBuyer"}
ALL_READ_ROLES = ["FilmOfficeAdmin", "FilmOfficeReviewer", "Producer", "CPAAuditor", "CreditBuyer"]


class Caller:
    def __init__(self, user_id: str, role: str):
        self.user_id = user_id
        self.role = role


def get_caller() -> Caller:
    """Priority 1: X-User-ID and X-User-Role present and well-formed.

    A role value outside the five recognized roles is malformed.
    """
    user_id = request.headers.get("X-User-ID", "").strip()
    role = request.headers.get("X-User-Role", "").strip()
    if not user_id or not role or role not in ALL_ROLES:
        raise_error(
            ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            "X-User-ID and X-User-Role headers must both be present and well-formed",
        )
    return Caller(user_id, role)


def check_role_allowed(caller: Caller, allowed_roles):
    """Priority 2: caller role must be on the endpoint's authorized list."""
    if caller.role not in allowed_roles:
        raise_error(
            ERR_FORBIDDEN_FOR_ROLE,
            f"role {caller.role} is not authorized for this endpoint",
        )


def authorized(allowed_roles) -> Caller:
    caller = get_caller()
    check_role_allowed(caller, allowed_roles)
    return caller
