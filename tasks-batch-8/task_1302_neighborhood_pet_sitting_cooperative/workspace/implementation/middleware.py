"""Auth header extraction and role checking (PRD §2.1, §2.7 steps 1-2)."""

from flask import request

from errors import (
    ApiError,
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
    ERR_UNAUTHORIZED,
)

ROLE_ANONYMOUS = "Anonymous"
ROLE_ADMIN = "CoopAdmin"
ROLE_MEMBER = "Member"
VALID_ROLES = {ROLE_ANONYMOUS, ROLE_ADMIN, ROLE_MEMBER}


def auth_ctx():
    """Validate X-User-ID / X-User-Role headers; return (user_id, role)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if (
        user_id is None
        or not isinstance(user_id, str)
        or not user_id.strip()
        or role is None
        or role not in VALID_ROLES
    ):
        raise ApiError(
            ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            400,
            "X-User-ID and X-User-Role headers must be present and well-formed",
        )
    return user_id, role


def require_roles(*allowed):
    """Pipeline steps 1-2: header presence/well-formedness, then RBAC."""
    user_id, role = auth_ctx()
    if role not in allowed:
        raise ApiError(
            ERR_UNAUTHORIZED,
            403,
            f"Role {role} is not permitted for this endpoint",
        )
    return user_id, role


def body():
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def pagination_params():
    """limit (default 10, min 1, max 100) and offset (default 0)."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    try:
        limit = int(raw_limit) if raw_limit is not None else 10
    except (TypeError, ValueError):
        limit = 10
    try:
        offset = int(raw_offset) if raw_offset is not None else 0
    except (TypeError, ValueError):
        offset = 0
    limit = max(1, min(100, limit))
    offset = max(0, offset)
    return limit, offset


def paginate(items, view):
    """Sort by created_at ascending (insertion order tiebreak) and paginate."""
    from response import ok_list

    ordered = sorted(items, key=lambda e: (e["created_at"], e.get("_seq", 0)))
    limit, offset = pagination_params()
    total = len(ordered)
    page = ordered[offset : offset + limit]
    return ok_list([view(e) for e in page], total, limit, offset)


def bool_filter(raw):
    if raw is None:
        return None
    text = str(raw).strip().lower()
    if text == "true":
        return True
    if text == "false":
        return False
    return None
