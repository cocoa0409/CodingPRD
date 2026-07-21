"""Auth header extraction, RBAC and body shape validation helpers.

PRD §2.1 pins the header names: X-User-ID and X-User-Role.
PRD §2.8 pins the order of evaluation for rejections.
"""
import functools

from flask import g, request

import db
from errors import err


def authenticate():
    """Step 1 of PRD §2.8."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in db.ROLES:
        raise err("ERR_UNAUTHENTICATED")
    g.user_id = user_id
    g.role = role
    return user_id, role


def authorize(*allowed_roles):
    """Step 2 of PRD §2.8."""
    if g.role not in allowed_roles:
        raise err("ERR_UNAUTHORIZED")


def require(*allowed_roles):
    """Decorator combining authentication + authorization."""
    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            authenticate()
            authorize(*allowed_roles)
            return fn(*args, **kwargs)
        return wrapper
    return decorator


def owns(claimant_id):
    """Step 3 of PRD §2.8 - ownership for the two entity-backed roles."""
    if g.role in db.CLAIMANT_ROLES and g.user_id != claimant_id:
        raise err("ERR_NOT_CLAIM_OWNER")


# ---------------------------------------------------------------------------
# Body shape validation (step 6 of PRD §2.8 -> ERR_VALIDATION)
# ---------------------------------------------------------------------------
def body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise err("ERR_VALIDATION", "Request body must be a JSON object.")
    return data


def require_fields(data, *names):
    for name in names:
        if name not in data or data[name] is None:
            raise err("ERR_VALIDATION", "Field '%s' is required." % name)


def as_string(data, name, required=True, allow_empty=False):
    if name not in data or data[name] is None:
        if required:
            raise err("ERR_VALIDATION", "Field '%s' is required." % name)
        return None
    value = data[name]
    if not isinstance(value, str):
        raise err("ERR_VALIDATION", "Field '%s' must be a string." % name)
    if not allow_empty and value == "" and required:
        raise err("ERR_VALIDATION", "Field '%s' must not be empty." % name)
    return value


def as_int(data, name, required=True, positive=False, default=None):
    if name not in data or data[name] is None:
        if required:
            raise err("ERR_VALIDATION", "Field '%s' is required." % name)
        return default
    value = data[name]
    if isinstance(value, bool) or not isinstance(value, int):
        raise err("ERR_VALIDATION", "Field '%s' must be an integer." % name)
    if positive and value <= 0:
        raise err("ERR_VALIDATION", "Field '%s' must be greater than zero." % name)
    return value


def as_bool(data, name, default=None):
    if name not in data or data[name] is None:
        return default
    value = data[name]
    if not isinstance(value, bool):
        raise err("ERR_VALIDATION", "Field '%s' must be a boolean." % name)
    return value


def as_enum(data, name, allowed, required=True, default=None):
    if name not in data or data[name] is None:
        if required:
            raise err("ERR_VALIDATION", "Field '%s' is required." % name)
        return default
    value = data[name]
    if not isinstance(value, str) or value not in allowed:
        raise err("ERR_VALIDATION", "Field '%s' must be one of %s." % (name, sorted(allowed)))
    return value


def as_datetime(data, name, required=True):
    if name not in data or data[name] is None:
        if required:
            raise err("ERR_VALIDATION", "Field '%s' is required." % name)
        return None
    parsed = db.parse_iso(data[name])
    if parsed is None:
        raise err("ERR_VALIDATION", "Field '%s' must be an ISO-8601 instant." % name)
    return parsed
