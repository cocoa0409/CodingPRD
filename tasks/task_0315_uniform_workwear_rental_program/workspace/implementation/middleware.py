"""Auth header extraction, RBAC, and pagination parsing.

Auth headers per PRD §2.1: X-User-ID (opaque operator id) and X-User-Role.
A request is authenticated iff X-User-Role names one of the four declared roles.
Identity is opaque and never compared to entity ids (§2.1).
"""
from flask import request

import errors

VALID_ROLES = {"ProgramAdmin", "AccountManager", "RouteDriver", "CleanroomTech"}


def get_role():
    """Return the acting role or raise ERR_UNAUTHENTICATED.

    Authentication (priority 1) keys solely on X-User-Role being a declared
    role per PRD §2.1: 'If X-User-Role is missing or does not name one of the
    declared roles, the request is rejected with ERR_UNAUTHENTICATED.'
    """
    role = request.headers.get("X-User-Role")
    if role is None or role not in VALID_ROLES:
        raise errors.unauthenticated()
    return role


def require_role(role, allowed):
    """Authorization (priority 2). Raise ERR_FORBIDDEN_ROLE if not permitted."""
    if role not in allowed:
        raise errors.forbidden()


# Pagination bounds (PRD §2.3 / SCAFFOLD §1.0 pagination_defaults).
LIMIT_DEFAULT = 10
LIMIT_MIN = 1
LIMIT_MAX = 100
OFFSET_DEFAULT = 0
OFFSET_MIN = 0


def parse_pagination():
    """Parse and validate limit/offset query params.

    Out-of-bounds or non-integer values raise ERR_PAGINATION_INVALID (400).
    """
    args = request.args
    limit = LIMIT_DEFAULT
    offset = OFFSET_DEFAULT

    if "limit" in args:
        raw = args.get("limit")
        try:
            limit = int(raw)
        except (TypeError, ValueError):
            raise errors.pagination_invalid()
        if limit < LIMIT_MIN or limit > LIMIT_MAX:
            raise errors.pagination_invalid()

    if "offset" in args:
        raw = args.get("offset")
        try:
            offset = int(raw)
        except (TypeError, ValueError):
            raise errors.pagination_invalid()
        if offset < OFFSET_MIN:
            raise errors.pagination_invalid()

    return limit, offset


def paginate(rows, limit, offset):
    """Apply the window after sorting by created_at asc (caller pre-sorts)."""
    total = len(rows)
    page = rows[offset:offset + limit]
    return page, total
