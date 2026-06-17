"""Auth extraction, RBAC, and request-shape helpers.

PRD §2.1: every request authenticates through X-User-ID and X-User-Role.
The five valid roles are exactly: SchoolAdmin, Dispatcher, Student, Instructor,
Mechanic.
"""

from flask import request

import errors
from errors import err

VALID_ROLES = {"SchoolAdmin", "Dispatcher", "Student", "Instructor", "Mechanic"}


def get_user_context():
    """Return (user_id, role) or raise ERR_MISSING_OR_INVALID_USER_CONTEXT.

    Validation order per §2.11: auth (this) is priority 1.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in VALID_ROLES:
        raise err(errors.ERR_MISSING_OR_INVALID_USER_CONTEXT,
                  "Missing or invalid X-User-ID / X-User-Role.")
    return user_id, role


def require_role(role, allowed):
    """Authorization (priority 2). Raise ERR_INSUFFICIENT_PERMISSIONS if the
    role is not in the allowed set for the operation."""
    if role not in allowed:
        raise err(errors.ERR_INSUFFICIENT_PERMISSIONS,
                  "Role is not permitted to perform this operation.")


def get_body():
    """Parse the JSON body, tolerating an absent/empty body as {}."""
    if not request.data:
        return {}
    data = request.get_json(silent=True)
    if data is None:
        # A body was supplied but is not valid JSON.
        raise err(errors.ERR_INVALID_REQUEST, "Request body is not valid JSON.")
    if not isinstance(data, dict):
        raise err(errors.ERR_INVALID_REQUEST, "Request body must be a JSON object.")
    return data


def parse_pagination():
    """Read limit/offset query params with PRD §2.3 defaults and clamping.

    limit defaults to 10, min 1, max 100. offset defaults to 0.
    Malformed values raise ERR_INVALID_REQUEST.
    """
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")

    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise err(errors.ERR_INVALID_REQUEST, "limit must be an integer.")
        if limit < 1:
            limit = 1
        elif limit > 100:
            limit = 100

    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise err(errors.ERR_INVALID_REQUEST, "offset must be an integer.")
        if offset < 0:
            offset = 0

    return limit, offset


def require_fields(body, fields):
    """Ensure required fields are present and non-None. ERR_INVALID_REQUEST."""
    for f in fields:
        if f not in body or body[f] is None:
            raise err(errors.ERR_INVALID_REQUEST, f"Missing required field: {f}.")


def as_number(body, field, required=True):
    if field not in body or body[field] is None:
        if required:
            raise err(errors.ERR_INVALID_REQUEST, f"Missing required field: {field}.")
        return None
    val = body[field]
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise err(errors.ERR_INVALID_REQUEST, f"{field} must be a number.")
    return val


def as_int(body, field, required=True):
    if field not in body or body[field] is None:
        if required:
            raise err(errors.ERR_INVALID_REQUEST, f"Missing required field: {field}.")
        return None
    val = body[field]
    if isinstance(val, bool):
        raise err(errors.ERR_INVALID_REQUEST, f"{field} must be an integer.")
    if isinstance(val, int):
        return val
    if isinstance(val, float) and val.is_integer():
        return int(val)
    raise err(errors.ERR_INVALID_REQUEST, f"{field} must be an integer.")


def as_str(body, field, required=True):
    if field not in body or body[field] is None:
        if required:
            raise err(errors.ERR_INVALID_REQUEST, f"Missing required field: {field}.")
        return None
    val = body[field]
    if not isinstance(val, str) or val == "":
        raise err(errors.ERR_INVALID_REQUEST, f"{field} must be a non-empty string.")
    return val


def enum_or_400(value, allowed, field):
    if value not in allowed:
        raise err(errors.ERR_INVALID_REQUEST, f"{field} must be one of {sorted(allowed)}.")
    return value
