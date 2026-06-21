"""Auth, RBAC, and body well-formedness helpers (PRD §2.1, §2.6)."""
from flask import request

from errors import err

ROLES = {"PermitClerk", "Inspector", "EnforcementOfficer", "HealthDirector"}


def require_auth():
    """Priority 1: X-User-ID and X-User-Role present and non-empty."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role:
        raise err("ERR_MISSING_USER_CONTEXT", "Missing X-User-ID or X-User-Role")
    return user_id, role


def require_role(role, allowed):
    """Priority 2: role permitted for this operation."""
    if role not in allowed:
        raise err("ERR_FORBIDDEN_ROLE", "Role %s not permitted for this operation" % role)


def auth(allowed_roles):
    """Combined: returns (user_id, role) after auth + RBAC checks."""
    user_id, role = require_auth()
    require_role(role, allowed_roles)
    return user_id, role


def get_body():
    if request.method in ("POST", "PUT", "DELETE", "PATCH"):
        data = request.get_json(silent=True)
        if data is None:
            return {}
        if not isinstance(data, dict):
            raise err("ERR_INVALID_REQUEST", "Request body must be a JSON object")
        return data
    return {}


# ---- well-formedness helpers (ERR_INVALID_REQUEST, 400) ----

def require_field(body, name):
    if name not in body or body[name] is None:
        raise err("ERR_INVALID_REQUEST", "Missing required field: %s" % name)
    return body[name]


def require_str(body, name):
    val = require_field(body, name)
    if not isinstance(val, str) or val == "":
        raise err("ERR_INVALID_REQUEST", "Field %s must be a non-empty string" % name)
    return val


def optional_str(body, name, default=None):
    if name not in body or body[name] is None:
        return default
    val = body[name]
    if not isinstance(val, str):
        raise err("ERR_INVALID_REQUEST", "Field %s must be a string" % name)
    return val


def require_int(body, name, minimum=None, maximum=None):
    val = require_field(body, name)
    val = _coerce_int(name, val)
    _check_range(name, val, minimum, maximum)
    return val


def optional_int(body, name, default=None, minimum=None, maximum=None):
    if name not in body or body[name] is None:
        return default
    val = _coerce_int(name, body[name])
    _check_range(name, val, minimum, maximum)
    return val


def _coerce_int(name, val):
    if isinstance(val, bool) or not isinstance(val, int):
        raise err("ERR_INVALID_REQUEST", "Field %s must be an integer" % name)
    return val


def _check_range(name, val, minimum, maximum):
    if minimum is not None and val < minimum:
        raise err("ERR_INVALID_REQUEST", "Field %s below minimum %s" % (name, minimum))
    if maximum is not None and val > maximum:
        raise err("ERR_INVALID_REQUEST", "Field %s above maximum %s" % (name, maximum))


def optional_bool(body, name, default=False):
    if name not in body or body[name] is None:
        return default
    val = body[name]
    if not isinstance(val, bool):
        raise err("ERR_INVALID_REQUEST", "Field %s must be a boolean" % name)
    return val


def require_enum(body, name, allowed):
    val = require_field(body, name)
    if val not in allowed:
        raise err("ERR_INVALID_REQUEST", "Field %s must be one of %s" % (name, sorted(allowed)))
    return val
