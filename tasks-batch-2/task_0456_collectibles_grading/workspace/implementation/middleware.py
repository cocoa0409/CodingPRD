"""Auth header extraction, role checking, pagination parsing (PRD §2.1, §2.3, §2.6)."""
from flask import request

from errors import err

VALID_ROLES = {"Anonymous", "Customer", "Receiver", "Grader", "Authenticator", "LabAdmin"}


def get_identity():
    """Extract (user_id, role) from headers, validating presence/well-formedness.

    PRD §2.1: every request other than customer registration and the test-clock
    control endpoint must carry X-User-ID and X-User-Role. Missing/malformed ->
    ERR_UNAUTHENTICATED.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role:
        raise err("ERR_UNAUTHENTICATED", "Missing X-User-ID or X-User-Role header.")
    if role not in VALID_ROLES:
        raise err("ERR_UNAUTHENTICATED", "Invalid X-User-Role header.")
    return user_id, role


def require_roles(role, allowed):
    """RBAC check (PRD §2.1): named role must be permitted -> else ERR_FORBIDDEN_ROLE."""
    if role not in allowed:
        raise err("ERR_FORBIDDEN_ROLE", "Role {} not permitted for this operation.".format(role))


def parse_pagination():
    """Parse limit/offset query params (PRD §2.3).

    limit defaults to 10, min 1, max 100. offset defaults to 0.
    Out-of-bounds -> ERR_PAGINATION_INVALID.
    """
    args = request.args
    limit_raw = args.get("limit")
    offset_raw = args.get("offset")

    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (ValueError, TypeError):
            raise err("ERR_PAGINATION_INVALID", "limit must be an integer.")
        if limit < 1 or limit > 100:
            raise err("ERR_PAGINATION_INVALID", "limit out of bounds [1,100].")

    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (ValueError, TypeError):
            raise err("ERR_PAGINATION_INVALID", "offset must be an integer.")
        if offset < 0:
            raise err("ERR_PAGINATION_INVALID", "offset must be >= 0.")

    return limit, offset


def paginate(items, limit, offset):
    """Slice a list after sorting by created_at asc (PRD §2.3)."""
    return items[offset:offset + limit]
