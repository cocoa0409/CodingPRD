"""Auth header extraction and RBAC."""

from functools import wraps
from flask import request
from errors import (
    APIError,
    ERR_AUTH_HEADERS_MISSING,
    ERR_ROLE_FORBIDDEN,
    ERR_BAD_REQUEST,
    HTTP_STATUS,
    raise_error,
)


VALID_ROLES = {
    "PlatformAdmin",
    "DistributorOps",
    "CinemaOps",
    "TicketingPlatform",
    "FinanceOps",
    "Auditor",
}


def get_auth():
    """Extract X-User-Role and X-User-ID. Raise ERR_AUTH_HEADERS_MISSING if missing/empty."""
    role = request.headers.get("X-User-Role", "").strip()
    user_id = request.headers.get("X-User-ID", "").strip()
    if not role or not user_id:
        raise_error(ERR_AUTH_HEADERS_MISSING, "X-User-Role and X-User-ID required")
    return role, user_id


def require_roles(allowed_roles):
    """Decorator factory: enforce that current role is among allowed_roles."""

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            role, _ = get_auth()
            if role not in allowed_roles:
                raise_error(ERR_ROLE_FORBIDDEN, f"Role {role} not authorized")
            return fn(*args, **kwargs)

        return wrapper

    return decorator


def parse_json_body():
    """Return parsed body or {} if empty. Raise ERR_BAD_REQUEST if malformed JSON."""
    if not request.data:
        return {}
    try:
        body = request.get_json(force=True, silent=False)
    except Exception:
        raise_error(ERR_BAD_REQUEST, "Malformed JSON")
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise_error(ERR_BAD_REQUEST, "Body must be a JSON object")
    return body


def require_fields(body, fields):
    """Raise ERR_BAD_REQUEST if any of fields is missing from body."""
    for f in fields:
        if f not in body:
            raise_error(ERR_BAD_REQUEST, f"Missing required field: {f}")


def require_int(value, field_name, min_v=None, max_v=None, allow_none=False):
    if value is None:
        if allow_none:
            return None
        raise_error(ERR_BAD_REQUEST, f"Field {field_name} is required")
    if isinstance(value, bool) or not isinstance(value, int):
        raise_error(ERR_BAD_REQUEST, f"Field {field_name} must be integer")
    if min_v is not None and value < min_v:
        raise_error(ERR_BAD_REQUEST, f"Field {field_name} below minimum {min_v}")
    if max_v is not None and value > max_v:
        raise_error(ERR_BAD_REQUEST, f"Field {field_name} above maximum {max_v}")
    return value


def require_str(value, field_name, allow_none=False, allow_empty=False):
    if value is None:
        if allow_none:
            return None
        raise_error(ERR_BAD_REQUEST, f"Field {field_name} is required")
    if not isinstance(value, str):
        raise_error(ERR_BAD_REQUEST, f"Field {field_name} must be string")
    if not allow_empty and not value.strip():
        raise_error(ERR_BAD_REQUEST, f"Field {field_name} must not be empty")
    return value


def require_enum(value, field_name, allowed, allow_none=False):
    if value is None:
        if allow_none:
            return None
        raise_error(ERR_BAD_REQUEST, f"Field {field_name} is required")
    if value not in allowed:
        raise_error(ERR_BAD_REQUEST, f"Field {field_name} must be one of {sorted(allowed)}")
    return value
