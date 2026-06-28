"""Auth header extraction, RBAC checks, pagination & body parsing helpers.

Auth headers (PRD §2.1, SCAFFOLD validation priority 1-2):
  - X-User-ID  : acting user id (mandatory, non-empty)
  - X-User-Role: one of the six recognized roles spelled exactly
"""

from flask import request

import errors
from errors import ApiError

VALID_ROLES = {
    "PlatformAdmin",
    "Inspector",
    "MitigationDesigner",
    "CrewLead",
    "ComplianceOfficer",
    "ClientContact",
}


def get_user_context():
    """Validate and return (user_id, role). Raises ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER
    (400) when either header is missing or malformed (priority 1)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or role is None:
        raise ApiError(
            errors.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            400,
            "X-User-ID and X-User-Role headers are required.",
        )
    if not isinstance(user_id, str) or user_id.strip() == "":
        raise ApiError(
            errors.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            400,
            "X-User-ID header is malformed.",
        )
    if role not in VALID_ROLES:
        raise ApiError(
            errors.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            400,
            "X-User-Role header is malformed.",
        )
    return user_id, role


def require_role(role, allowed):
    """Enforce RBAC (priority 2). Raises ERR_FORBIDDEN_FOR_ROLE (403) when the
    caller's role is not in the allowed set for this endpoint."""
    if role not in allowed:
        raise ApiError(
            errors.ERR_FORBIDDEN_FOR_ROLE,
            403,
            "Role '%s' is not permitted for this operation." % role,
        )


def get_json_body():
    """Return the parsed JSON body as a dict, or {} when no body was supplied.
    A body that is present but not a JSON object is ERR_INVALID_REQUEST."""
    if not request.data:
        return {}
    try:
        data = request.get_json(force=True, silent=False)
    except Exception:
        raise ApiError(errors.ERR_INVALID_REQUEST, 400, "Request body is not valid JSON.")
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError(errors.ERR_INVALID_REQUEST, 400, "Request body must be a JSON object.")
    return data


def parse_pagination():
    """Parse limit/offset query params per PRD §2.3.
    limit default 10, min 1, max 100; offset default 0, min 0.
    Out-of-range or non-integer -> ERR_PAGINATION_INVALID (400)."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")

    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise ApiError(errors.ERR_PAGINATION_INVALID, 400, "limit must be an integer.")
        if limit < 1 or limit > 100:
            raise ApiError(errors.ERR_PAGINATION_INVALID, 400, "limit must be between 1 and 100.")

    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise ApiError(errors.ERR_PAGINATION_INVALID, 400, "offset must be an integer.")
        if offset < 0:
            raise ApiError(errors.ERR_PAGINATION_INVALID, 400, "offset must be >= 0.")

    return limit, offset
