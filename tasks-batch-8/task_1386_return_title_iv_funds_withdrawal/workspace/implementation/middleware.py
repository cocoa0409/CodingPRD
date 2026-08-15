"""Auth context extraction and role checking (PRD §2.1, SCAFFOLD §1.4 p1-p2).

Headers: X-User-ID and X-User-Role. Role must be one of the five declared
roles. Endpoints declare their allowed roles; "Any" means all five roles
(any authenticated caller).
"""

from flask import request

import errors

ROLES = ["SystemAdmin", "RegistrarClerk", "FinancialAidOfficer", "BursarClerk", "Student"]
ALL_ROLES = list(ROLES)


class AuthContext:
    def __init__(self, user_id: str, role: str):
        self.user_id = user_id
        self.role = role

    @property
    def is_student(self) -> bool:
        return self.role == "Student"


def get_auth() -> AuthContext:
    """Priority 1: headers present and role declared."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        errors.raise_error(
            errors.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            "X-User-ID and X-User-Role headers are required and role must be a declared role",
        )
    return AuthContext(user_id, role)


def require_roles(auth: AuthContext, allowed):
    """Priority 2: role listed for the endpoint."""
    if auth.role not in allowed:
        errors.raise_error(
            errors.ERR_FORBIDDEN_FOR_ROLE,
            f"Role {auth.role} is not permitted for this operation",
        )


def parse_json_body():
    """Return the request JSON body as a dict, or raise ERR_INVALID_REQUEST."""
    body = request.get_json(silent=True)
    if body is None:
        body = {}
    if not isinstance(body, dict):
        errors.raise_error(errors.ERR_INVALID_REQUEST, "Request body must be a JSON object")
    return body


def parse_pagination(args):
    """Read limit/offset query params per SCAFFOLD pagination fields."""
    limit = response_limit(args.get("limit"))
    offset = response_offset(args.get("offset"))
    return limit, offset


def response_limit(raw):
    if raw is None:
        return 10
    try:
        value = int(raw)
    except (TypeError, ValueError):
        errors.raise_error(errors.ERR_INVALID_FIELD, "limit must be an integer")
    if value < 1 or value > 100:
        errors.raise_error(errors.ERR_INVALID_FIELD, "limit must be between 1 and 100")
    return value


def response_offset(raw):
    if raw is None:
        return 0
    try:
        value = int(raw)
    except (TypeError, ValueError):
        errors.raise_error(errors.ERR_INVALID_FIELD, "offset must be an integer")
    if value < 0:
        errors.raise_error(errors.ERR_INVALID_FIELD, "offset must be >= 0")
    return value
