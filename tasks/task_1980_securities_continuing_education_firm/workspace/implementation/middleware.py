"""Auth context extraction + role authorization (PRD 2.1, validation steps 1-2)."""

from functools import wraps

from flask import g, request

from errors import ApiError, ERR_AUTH_CONTEXT, ERR_UNAUTHORIZED_ROLE, ERR_INVALID_REQUEST

ROLES = ("TrainingAdmin", "ComplianceOfficer", "RegisteredRep", "Auditor")

ANY_ROLE = ROLES


def require_roles(*allowed):
    """Validate X-User-ID / X-User-Role, then enforce the endpoint role list."""
    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_id = request.headers.get("X-User-ID")
            role = request.headers.get("X-User-Role")
            if not user_id or not isinstance(user_id, str) \
                    or not role or role not in ROLES:
                raise ApiError(ERR_AUTH_CONTEXT, 400,
                               "X-User-ID and X-User-Role headers are required and "
                               "X-User-Role must be one of " + ", ".join(ROLES))
            if role not in allowed:
                raise ApiError(ERR_UNAUTHORIZED_ROLE, 403,
                               "Role %s is not permitted on this endpoint" % role)
            g.actor_user_id = user_id
            g.actor_role = role
            return fn(*args, **kwargs)
        return wrapper
    return deco


def actor():
    return (g.actor_user_id, g.actor_role)


def json_body():
    """Return the request JSON object; an absent body is an empty object."""
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise ApiError(ERR_INVALID_REQUEST, 400, "Request body must be a JSON object")
    return body


def require_fields(body, *fields):
    for f in fields:
        if f not in body or body[f] is None:
            raise ApiError(ERR_INVALID_REQUEST, 400,
                           "Missing required field '%s'" % f)
