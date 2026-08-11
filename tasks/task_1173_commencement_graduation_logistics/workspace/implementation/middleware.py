"""Auth header extraction and role checking per PRD §2.1 and scaffold validations 1-2, 5-6."""
from flask import request

from errors import raise_err, ERR_UNAUTHENTICATED, ERR_UNAUTHORIZED_ROLE, ERR_FORBIDDEN_OWNERSHIP

VALID_ROLES = {"CommitteeChair", "RegistrarOfficer", "VenueCoordinator", "Graduate", "Vendor"}


def get_caller():
    """Validate X-User-ID / X-User-Role headers. Returns (user_id, role)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in VALID_ROLES:
        raise_err(ERR_UNAUTHENTICATED, "Missing or invalid X-User-ID / X-User-Role headers")
    return user_id, role


def require_role(role, allowed):
    if role not in allowed:
        raise_err(ERR_UNAUTHORIZED_ROLE, f"Role {role} is not authorized for this endpoint")


def require_graduate_ownership(user_id, role, graduate_id):
    """Graduate role may only touch resources whose graduate chain matches their own id."""
    if role == "Graduate" and user_id != graduate_id:
        raise_err(ERR_FORBIDDEN_OWNERSHIP, "Graduate may only access own resources")


def get_json_body(required=True):
    body = request.get_json(silent=True)
    if body is None:
        if required:
            from errors import raise_err as re_, ERR_INVALID_REQUEST
            re_(ERR_INVALID_REQUEST, "Request body must be valid JSON")
        return {}
    if not isinstance(body, dict):
        from errors import raise_err as re_, ERR_INVALID_REQUEST
        re_(ERR_INVALID_REQUEST, "Request body must be a JSON object")
    return body


def require_fields(body, fields):
    from errors import raise_err as re_, ERR_INVALID_REQUEST
    for f in fields:
        if f not in body or body[f] is None:
            re_(ERR_INVALID_REQUEST, f"Missing required field: {f}")
