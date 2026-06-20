"""Auth header extraction, RBAC, and request/pagination helpers.

Auth header names and role values come verbatim from PRD 2.1:
  - X-User-ID  (opaque string identifying the acting user)
  - X-User-Role (one of the five roles)
"""
from flask import request

from errors import err

USER_ID_HEADER = "X-User-ID"
USER_ROLE_HEADER = "X-User-Role"

# The exactly-five roles, spelled per PRD 2.1.
ROLES = {
    "SponsorAdmin",
    "ComplianceOfficer",
    "ContributionAdmin",
    "DonorAdvisor",
    "GrantOfficer",
}

# Pagination defaults (PRD 2.3 / SCAFFOLD 1.0).
PAGE_LIMIT_DEFAULT = 10
PAGE_LIMIT_MIN = 1
PAGE_LIMIT_MAX = 100
PAGE_OFFSET_DEFAULT = 0


def get_identity():
    """Validate and return (user_id, role).

    PRD 2.1: every request must carry X-User-ID and X-User-Role; if either is
    missing or malformed -> ERR_MISSING_USER_CONTEXT (400). A role that is not
    one of the five is malformed.
    """
    user_id = request.headers.get(USER_ID_HEADER)
    role = request.headers.get(USER_ROLE_HEADER)
    if not user_id or not isinstance(user_id, str) or not user_id.strip():
        raise err("ERR_MISSING_USER_CONTEXT")
    if not role or role not in ROLES:
        raise err("ERR_MISSING_USER_CONTEXT")
    return user_id, role


def require_role(role, allowed):
    """PRD 2.1: role present but not permitted for this endpoint -> ERR_FORBIDDEN_FOR_ROLE (403)."""
    if role not in allowed:
        raise err("ERR_FORBIDDEN_FOR_ROLE")


def get_json_body():
    """Parse the JSON body, tolerating an empty body for no-input POSTs."""
    if not request.data:
        return {}
    try:
        body = request.get_json(force=True, silent=True)
    except Exception:
        body = None
    if body is None:
        # An empty/whitespace body is acceptable (no-input action endpoints).
        if not request.data.strip():
            return {}
        raise err("ERR_INVALID_REQUEST")
    if not isinstance(body, dict):
        raise err("ERR_INVALID_REQUEST")
    return body


def get_pagination():
    """Read limit/offset from query params (PRD 2.3). limit clamped to [1,100];
    offset defaults to 0."""
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
    except (TypeError, ValueError):
        return default


def paginate(items, limit, offset):
    """Apply offset/limit and return (page, pagination_meta).

    PRD 2.3: total_count is the matching count before pagination; has_more is
    true when records remain beyond the current page.
    """
    total = len(items)
    page = items[offset:offset + limit]
    has_more = (offset + limit) < total
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": has_more,
    }
    return page, meta
