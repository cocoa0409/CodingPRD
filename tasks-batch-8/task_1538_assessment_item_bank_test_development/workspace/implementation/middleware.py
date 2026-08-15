"""Auth header extraction and role admissibility (PRD §2.1, validations 1-2)."""
from flask import request

from errors import (
    raise_error,
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
    ERR_INSUFFICIENT_PERMISSIONS,
)

ALL_ROLES = [
    "ProgramDirector",
    "ItemWriter",
    "ContentReviewer",
    "BiasSensitivityReviewer",
    "Psychometrician",
    "TestAssembler",
    "SecurityOfficer",
    "TranslationSpecialist",
]


class Caller:
    def __init__(self, user_id: str, role: str):
        self.user_id = user_id
        self.role = role


def get_caller() -> Caller:
    """Priority 1: X-User-ID and X-User-Role must be present and non-empty."""
    user_id = (request.headers.get("X-User-ID") or "").strip()
    role = (request.headers.get("X-User-Role") or "").strip()
    if not user_id or not role:
        raise_error(
            ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            "X-User-ID and X-User-Role headers must both be present and non-empty",
        )
    return Caller(user_id, role)


def require_roles(caller: Caller, allowed_roles):
    """Priority 2: role must be among the endpoint's declared roles."""
    if caller.role not in allowed_roles:
        raise_error(
            ERR_INSUFFICIENT_PERMISSIONS,
            f"role {caller.role} is not authorized for this endpoint",
        )
    return caller


def authorized(allowed_roles) -> Caller:
    caller = get_caller()
    require_roles(caller, allowed_roles)
    return caller
