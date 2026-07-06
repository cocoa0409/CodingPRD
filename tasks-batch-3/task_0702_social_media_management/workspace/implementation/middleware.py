"""Auth header extraction, role checking, request body parsing, pagination.

Header names and role values come from PRD §2.1:
  X-User-ID, X-User-Role
  roles: AccountManager, ContentCreator, Approver, CommunityAgent,
         FinanceController, PlatformAdmin
"""
from flask import request

from errors import (
    err, ERR_MISSING_USER_CONTEXT, ERR_FORBIDDEN_ROLE, ERR_INVALID_REQUEST,
)

VALID_ROLES = {
    "AccountManager",
    "ContentCreator",
    "Approver",
    "CommunityAgent",
    "FinanceController",
    "PlatformAdmin",
}


def get_user_context():
    """Validate the two mandatory auth headers (priority 1).

    Returns (user_id, role). Raises ERR_MISSING_USER_CONTEXT (401) when either is
    missing or malformed (empty / unrecognized role value).
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not user_id.strip():
        raise err(ERR_MISSING_USER_CONTEXT, "X-User-ID header missing or malformed")
    if not role or role not in VALID_ROLES:
        raise err(ERR_MISSING_USER_CONTEXT, "X-User-Role header missing or malformed")
    return user_id, role


def require_role(role, allowed):
    """Role authorization (priority 2). Raises ERR_FORBIDDEN_ROLE (403)."""
    if role not in allowed:
        raise err(ERR_FORBIDDEN_ROLE, "Role %s is not permitted for this operation" % role)


def get_json_body():
    """Parse the JSON request body, defaulting to an empty dict.

    A body that is present but not a JSON object is an ERR_INVALID_REQUEST.
    """
    if request.content_length in (None, 0):
        return {}
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise err(ERR_INVALID_REQUEST, "Request body must be a JSON object")
    return data


def get_pagination():
    """Parse limit/offset (PRD §2.3): limit default 10, min 1, max 100; offset default 0.

    Malformed values are rejected with ERR_INVALID_REQUEST (400).
    """
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit = 10
    offset = 0
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise err(ERR_INVALID_REQUEST, "limit must be an integer")
        if limit < 1 or limit > 100:
            raise err(ERR_INVALID_REQUEST, "limit must be between 1 and 100")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise err(ERR_INVALID_REQUEST, "offset must be an integer")
        if offset < 0:
            raise err(ERR_INVALID_REQUEST, "offset must be >= 0")
    return limit, offset


# ----- body field validation helpers (priority 18: ERR_INVALID_REQUEST) -----

def require_string(body, field):
    val = body.get(field)
    if not isinstance(val, str) or not val.strip():
        raise err(ERR_INVALID_REQUEST, "Field %s must be a non-empty string" % field)
    return val


def require_int(body, field):
    val = body.get(field)
    if isinstance(val, bool) or not isinstance(val, int):
        raise err(ERR_INVALID_REQUEST, "Field %s must be an integer" % field)
    return val


def require_enum(body, field, allowed):
    val = require_string(body, field)
    if val not in allowed:
        raise err(ERR_INVALID_REQUEST, "Field %s must be one of %s" % (field, sorted(allowed)))
    return val


def require_positive_int(body, field):
    val = require_int(body, field)
    if val <= 0:
        raise err(ERR_INVALID_REQUEST, "Field %s must be > 0" % field)
    return val


def require_nonneg_int(body, field):
    val = require_int(body, field)
    if val < 0:
        raise err(ERR_INVALID_REQUEST, "Field %s must be >= 0" % field)
    return val


def require_min_int(body, field, minimum):
    val = require_int(body, field)
    if val < minimum:
        raise err(ERR_INVALID_REQUEST, "Field %s must be >= %d" % (field, minimum))
    return val


def optional_int(body, field, default):
    if field not in body or body.get(field) is None:
        return default
    return require_int(body, field)
