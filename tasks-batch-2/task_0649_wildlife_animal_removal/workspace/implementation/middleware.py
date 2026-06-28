"""Auth extraction, RBAC, pagination, and body-field validation helpers.

Auth headers (PRD §2.1): X-User-ID and X-User-Role. Recognized roles are exactly
Dispatcher, PropertyOwner, FieldTechnician, ComplianceOfficer.
"""
from flask import request

from errors import err

ROLES = {"Dispatcher", "PropertyOwner", "FieldTechnician", "ComplianceOfficer"}


def auth():
    """Validate auth headers (priority 1). Returns (user_id, role)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise err("ERR_UNAUTHENTICATED", "Missing or invalid authentication headers.")
    return user_id, role


def require_role(role, allowed):
    """RBAC check (priority 2)."""
    if role not in allowed:
        raise err("ERR_FORBIDDEN_ROLE", "Role %s may not perform this operation." % role)


# ----- pagination (PRD §2.3) -----
def pagination():
    limit = _int_param("limit", 10)
    offset = _int_param("offset", 0)
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    return limit, offset


def _int_param(name, default):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def paginate(items, limit, offset):
    """items already sorted; returns the window."""
    return items[offset:offset + limit]


# ----- body parsing & field validation -----
def body():
    if request.method in ("POST", "PUT", "PATCH"):
        data = request.get_json(silent=True)
        if data is None:
            data = {}
        if not isinstance(data, dict):
            raise err("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
        return data
    return {}


def require_str(data, field):
    v = data.get(field)
    if not isinstance(v, str) or v == "":
        raise err("ERR_INVALID_REQUEST", "Field '%s' is required and must be a non-empty string." % field)
    return v


def opt_str(data, field, default=None):
    if field not in data or data[field] is None:
        return default
    v = data[field]
    if not isinstance(v, str):
        raise err("ERR_INVALID_REQUEST", "Field '%s' must be a string." % field)
    return v


def require_int(data, field, minimum=None):
    v = data.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise err("ERR_INVALID_REQUEST", "Field '%s' is required and must be an integer." % field)
    if minimum is not None and v < minimum:
        raise err("ERR_INVALID_REQUEST", "Field '%s' must be >= %s." % (field, minimum))
    return v


def opt_int(data, field, default, minimum=None):
    if field not in data or data[field] is None:
        return default
    v = data[field]
    if isinstance(v, bool) or not isinstance(v, int):
        raise err("ERR_INVALID_REQUEST", "Field '%s' must be an integer." % field)
    if minimum is not None and v < minimum:
        raise err("ERR_INVALID_REQUEST", "Field '%s' must be >= %s." % (field, minimum))
    return v


def require_number(data, field, minimum=None, maximum=None):
    v = data.get(field)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise err("ERR_INVALID_REQUEST", "Field '%s' is required and must be a number." % field)
    if minimum is not None and v < minimum:
        raise err("ERR_INVALID_REQUEST", "Field '%s' out of range." % field)
    if maximum is not None and v > maximum:
        raise err("ERR_INVALID_REQUEST", "Field '%s' out of range." % field)
    return v


def opt_number(data, field, default, minimum=None, maximum=None):
    if field not in data or data[field] is None:
        return default
    v = data[field]
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise err("ERR_INVALID_REQUEST", "Field '%s' must be a number." % field)
    if minimum is not None and v < minimum:
        raise err("ERR_INVALID_REQUEST", "Field '%s' out of range." % field)
    if maximum is not None and v > maximum:
        raise err("ERR_INVALID_REQUEST", "Field '%s' out of range." % field)
    return v


def require_bool(data, field, default=None):
    if field not in data or data[field] is None:
        if default is not None:
            return default
        raise err("ERR_INVALID_REQUEST", "Field '%s' is required and must be a boolean." % field)
    v = data[field]
    if not isinstance(v, bool):
        raise err("ERR_INVALID_REQUEST", "Field '%s' must be a boolean." % field)
    return v


def require_enum(data, field, allowed, default=None):
    if field not in data or data[field] is None:
        if default is not None:
            return default
        raise err("ERR_INVALID_REQUEST", "Field '%s' is required." % field)
    v = data[field]
    if v not in allowed:
        raise err("ERR_INVALID_REQUEST", "Field '%s' must be one of %s." % (field, sorted(allowed)))
    return v
