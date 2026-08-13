"""Auth middleware + pagination parsing.

Headers (per SCAFFOLD `validations` priority 1 and PRD §2.1):
  - X-User-ID   (required, non-empty)
  - X-User-Role (required, non-empty; must be one of Student, Advisor,
                 RegistrarStaff, SystemAdmin)
"""

from flask import request

from errors import ApiError

ROLES = ("Student", "Advisor", "RegistrarStaff", "SystemAdmin")


def get_auth():
    """Return (user_id, role). Raises ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.

    Validation 1: headers present + non-empty.
    Unknown role values are also malformed context (role must be one of the
    recognized four).
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role:
        raise ApiError(
            "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
            "X-User-ID and X-User-Role headers must be present and non-empty.",
        )
    if role not in ROLES:
        # An unrecognized role cannot be matched against any endpoint grant.
        raise ApiError(
            "ERR_FORBIDDEN",
            "Role not permitted.",
        )
    return user_id, role


def require_roles(role, allowed):
    """Validation 2: endpoint-level role grant."""
    if role not in allowed:
        raise ApiError("ERR_FORBIDDEN", "Role not permitted for this endpoint.")


def require_owner(user_id, owner_student_id):
    """Validation 2: Student may only touch own records."""
    if user_id != owner_student_id:
        raise ApiError("ERR_FORBIDDEN", "Student may only act on own records.")


def parse_pagination():
    """Parse limit/offset per SCAFFOLD pagination_defaults.

    Defaults: limit=10, offset=0; limit in [1,100]; offset >= 0.
    """
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    try:
        limit = int(raw_limit) if raw_limit is not None else 10
    except (TypeError, ValueError):
        raise ApiError("ERR_INVALID_PAGINATION_PARAMETERS", "limit must be an integer.")
    try:
        offset = int(raw_offset) if raw_offset is not None else 0
    except (TypeError, ValueError):
        raise ApiError("ERR_INVALID_PAGINATION_PARAMETERS", "offset must be an integer.")
    if limit < 1 or limit > 100 or offset < 0:
        raise ApiError(
            "ERR_INVALID_PAGINATION_PARAMETERS",
            "limit out of [1,100] or offset negative.",
        )
    return limit, offset
