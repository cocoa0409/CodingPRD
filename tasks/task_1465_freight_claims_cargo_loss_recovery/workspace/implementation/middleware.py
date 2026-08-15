"""Auth middleware (X-User-ID / X-User-Role) and request-body validators."""

from functools import wraps

from flask import g, request

from errors import (
    ApiError,
    ERR_INSUFFICIENT_PERMISSIONS,
    ERR_INVALID_ENUM,
    ERR_INVALID_REQUEST,
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
)

VALID_ROLES = {
    "PlatformAdmin",
    "ClaimsClerk",
    "ClaimsAdjuster",
    "ClaimsManager",
    "SalvageCoordinator",
    "SubrogationSpecialist",
    "FinanceController",
}


def require_roles(*allowed):
    """Validate auth headers (400) then endpoint role membership (403).

    "Any" in allowed means every authenticated role may proceed.
    """
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_id = request.headers.get("X-User-ID")
            role = request.headers.get("X-User-Role")
            if (not user_id or not user_id.strip()
                    or not role or role not in VALID_ROLES):
                raise ApiError(
                    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
                    "X-User-ID and X-User-Role headers must be present and well-formed",
                    400,
                )
            if "Any" not in allowed and role not in allowed:
                raise ApiError(
                    ERR_INSUFFICIENT_PERMISSIONS,
                    f"Role '{role}' is not permitted to invoke this operation",
                    403,
                )
            g.user_id = user_id
            g.role = role
            return fn(*args, **kwargs)
        return wrapper
    return decorator


def request_body():
    """Return the JSON request body as a dict; {} when no body was sent."""
    if not request.data:
        return {}
    try:
        parsed = request.get_json(force=True, silent=False)
    except Exception:
        raise ApiError(ERR_INVALID_REQUEST, "Request body must be valid JSON", 400)
    if parsed is None:
        return {}
    if not isinstance(parsed, dict):
        raise ApiError(ERR_INVALID_REQUEST, "Request body must be a JSON object", 400)
    return parsed


def req_field(body, name):
    if name not in body or body[name] is None:
        raise ApiError(ERR_INVALID_REQUEST, f"Missing required field: '{name}'", 400)
    return body[name]


def as_int(value, name):
    if isinstance(value, bool) or not isinstance(value, int):
        raise ApiError(ERR_INVALID_REQUEST, f"Field '{name}' must be an integer", 400)
    return value


def as_str(value, name):
    if not isinstance(value, str) or not value:
        raise ApiError(ERR_INVALID_REQUEST, f"Field '{name}' must be a non-empty string", 400)
    return value


def as_bool(value, name):
    if not isinstance(value, bool):
        raise ApiError(ERR_INVALID_REQUEST, f"Field '{name}' must be a boolean", 400)
    return value


def as_enum(value, name, allowed):
    if not isinstance(value, str) or value not in allowed:
        raise ApiError(
            ERR_INVALID_ENUM,
            f"Field '{name}' must be one of: {', '.join(sorted(allowed))}",
            400,
        )
    return value


def opt_int(body, name):
    if name not in body or body[name] is None:
        return None
    return as_int(body[name], name)
