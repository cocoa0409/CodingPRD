"""Auth header extraction, RBAC, pagination, body parsing (PRD §2.1, §2.3, §2.7)."""

from flask import request

import errors

# The five declared roles, spelled precisely (PRD §2.1).
ROLES = {"PracticeAdmin", "Podiatrist", "BillingSpecialist", "FrontDesk", "PayerAgent"}


def authenticate():
    """Validate X-User-ID and X-User-Role headers (PRD §2.1, validation priority 1).

    Returns (user_id, role). Raises ERR_MISSING_OR_INVALID_USER_CONTEXT (401) when
    either header is absent or the role is not one of the five declared roles.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise errors.missing_user_context()
    return user_id, role


def require_role(role, allowed):
    """RBAC check (PRD §2.1, validation priority 2).

    allowed is an iterable of role names permitted for this operation. Raises
    ERR_FORBIDDEN_ROLE (403) when role is authenticated but not permitted.
    """
    if role not in allowed:
        raise errors.forbidden_role()


def get_body():
    """Parse JSON body, tolerating an empty/absent body (returns {})."""
    if not request.data:
        return {}
    data = request.get_json(silent=True)
    if data is None:
        # Body present but not valid JSON -> treat as structural validation error.
        raise errors.invalid_request("Request body must be valid JSON.")
    if not isinstance(data, dict):
        raise errors.invalid_request("Request body must be a JSON object.")
    return data


# Pagination (PRD §2.3): limit default 10, min 1, max 100; offset default 0.
PAGE_LIMIT_DEFAULT = 10
PAGE_LIMIT_MIN = 1
PAGE_LIMIT_MAX = 100
PAGE_OFFSET_DEFAULT = 0


def get_pagination():
    """Return (limit, offset) parsed from query params, clamped to PRD bounds."""
    limit = _parse_int_param("limit", PAGE_LIMIT_DEFAULT)
    offset = _parse_int_param("offset", PAGE_OFFSET_DEFAULT)
    if limit < PAGE_LIMIT_MIN:
        limit = PAGE_LIMIT_MIN
    if limit > PAGE_LIMIT_MAX:
        limit = PAGE_LIMIT_MAX
    if offset < 0:
        offset = 0
    return limit, offset


def _parse_int_param(name, default):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except (ValueError, TypeError):
        return default


def paginate(items):
    """Sort by created_at asc (PRD §2.3), apply limit/offset, return (page, meta)."""
    ordered = sorted(items, key=lambda e: (e["created_at"], e.get("_seq", 0)))
    total = len(ordered)
    limit, offset = get_pagination()
    page = ordered[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    return page, meta
