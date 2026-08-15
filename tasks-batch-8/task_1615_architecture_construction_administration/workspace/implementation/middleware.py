"""Auth header extraction and role checking (scaffold validations priority 1-2)."""

from flask import request

from errors import (
    ApiError,
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
    ERR_FORBIDDEN_ROLE,
)

ROLES = ("FirmAdmin", "ArchitectCA", "Contractor", "Owner")


def get_user_context():
    """Validate X-User-ID and X-User-Role headers; return (user_id, role)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if (
        user_id is None
        or role is None
        or not str(user_id).strip()
        or not str(role).strip()
        or role not in ROLES
    ):
        raise ApiError(
            ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            "X-User-ID and X-User-Role headers must both be present and non-empty, "
            "and X-User-Role must be one of the declared roles",
            400,
        )
    return user_id, role


def require_role(role: str, allowed: tuple | list):
    if role not in allowed:
        raise ApiError(
            ERR_FORBIDDEN_ROLE,
            "Role is not in the endpoint's allowed roles",
            403,
        )


def get_body(required: bool = False) -> dict:
    """Return the JSON request body; raise ERR_INVALID_REQUEST when malformed."""
    from errors import ERR_INVALID_REQUEST

    body = request.get_json(silent=True)
    if body is None:
        if required or (request.content_length or 0) > 0:
            raise ApiError(ERR_INVALID_REQUEST, "Request body must be a JSON object", 400)
        return {}
    if not isinstance(body, dict):
        raise ApiError(ERR_INVALID_REQUEST, "Request body must be a JSON object", 400)
    return body
