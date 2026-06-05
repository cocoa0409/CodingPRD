"""Auth header extraction, role validation, and pagination parsing.

Auth headers (PRD §2.1): X-User-ID and X-User-Role.
Declared roles, spelled exactly: Anonymous, Physician, Patient, LicensingBoard,
ComplianceOfficer.

Pagination (PRD §2.3): limit default 10, min 1, max 100; offset default 0, min 0.
Out-of-range → ERR_PAGINATION_INVALID (422).
"""
from flask import request

from errors import err, ERR_UNAUTHENTICATED, ERR_FORBIDDEN, ERR_PAGINATION_INVALID

DECLARED_ROLES = {"Anonymous", "Physician", "Patient", "LicensingBoard", "ComplianceOfficer"}

PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0


def get_identity():
    """Return (user_id, role) from request headers (may be None)."""
    return request.headers.get("X-User-ID"), request.headers.get("X-User-Role")


def require_auth():
    """Priority-1 auth check (ERR_UNAUTHENTICATED 401).

    Both headers must be present and the role must be a declared role.
    Returns (user_id, role).
    """
    user_id, role = get_identity()
    if not user_id or not role or role not in DECLARED_ROLES:
        raise err(ERR_UNAUTHENTICATED, "Missing or invalid authentication headers.")
    return user_id, role


def require_role(role, allowed_roles):
    """Priority-2 RBAC check (ERR_FORBIDDEN 403)."""
    if role not in allowed_roles:
        raise err(ERR_FORBIDDEN, "Role %s is not permitted for this operation." % role)


def parse_pagination():
    """Parse limit/offset query params. Raises ERR_PAGINATION_INVALID on bad values."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")

    if raw_limit is None:
        limit = PAGINATION_DEFAULT_LIMIT
    else:
        try:
            limit = int(raw_limit)
        except (ValueError, TypeError):
            raise err(ERR_PAGINATION_INVALID, "limit must be an integer.")
    if raw_offset is None:
        offset = PAGINATION_DEFAULT_OFFSET
    else:
        try:
            offset = int(raw_offset)
        except (ValueError, TypeError):
            raise err(ERR_PAGINATION_INVALID, "offset must be an integer.")

    if limit < PAGINATION_MIN_LIMIT or limit > PAGINATION_MAX_LIMIT:
        raise err(ERR_PAGINATION_INVALID, "limit must be within [1, 100].")
    if offset < 0:
        raise err(ERR_PAGINATION_INVALID, "offset must be >= 0.")
    return limit, offset


def paginate(items, limit, offset):
    """Slice an already-sorted list and return (page, total_count)."""
    total = len(items)
    page = items[offset:offset + limit]
    return page, total
