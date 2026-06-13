"""Auth header extraction, role checking, pagination parsing.

Auth headers per PRD §2.1: X-User-ID and X-User-Role. Roles are exactly
{Applicant, LicensingOfficer, InspectionOfficer}.
"""
from flask import request

import errors

KNOWN_ROLES = {"Applicant", "LicensingOfficer", "InspectionOfficer"}


class Identity:
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role


def authenticate():
    """Priority 1: both headers present and role is known. Else ERR_UNAUTHENTICATED (401)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in KNOWN_ROLES:
        raise errors.unauthenticated()
    return Identity(user_id, role)


def require_roles(identity, allowed_roles):
    """Priority 2: role permitted for this operation. Else ERR_UNAUTHORIZED (403)."""
    if identity.role not in allowed_roles:
        raise errors.unauthorized()


def parse_pagination():
    """Parse limit/offset query params per PRD §2.3.

    limit default 10, min 1, max 100. offset default 0, min 0.
    Out of range -> ERR_PAGINATION_INVALID (400).
    """
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")

    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (ValueError, TypeError):
            raise errors.pagination_invalid()
        if limit < 1 or limit > 100:
            raise errors.pagination_invalid()

    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (ValueError, TypeError):
            raise errors.pagination_invalid()
        if offset < 0:
            raise errors.pagination_invalid()

    return limit, offset


def paginate(items, limit, offset):
    """Slice a pre-sorted list and return (page, total_count)."""
    total = len(items)
    page = items[offset:offset + limit]
    return page, total
