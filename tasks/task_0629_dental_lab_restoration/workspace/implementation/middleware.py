"""Auth header extraction, role checking, pagination parsing (PRD §2.1, §2.3, §2.9)."""
from flask import request

import errors
from errors import err

# The five recognized roles, spelled precisely (PRD §2.1).
KNOWN_ROLES = {"Doctor", "LabTech", "Scheduler", "Billing", "LabAdmin"}


def authenticate():
    """Validate mandatory auth headers (PRD §2.1, validation priority 1).

    Every request must include X-User-ID and X-User-Role; X-User-Role must be
    one of the five known roles. Otherwise ERR_UNAUTHENTICATED (401).

    Returns (user_id, role).
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in KNOWN_ROLES:
        raise err(errors.ERR_UNAUTHENTICATED, "Missing or unknown authentication headers.")
    return user_id, role


def require_roles(role, allowed):
    """RBAC authorization (PRD §2.1, validation priority 2).

    If the authenticated role is not permitted for this endpoint -> ERR_FORBIDDEN_ROLE (403).
    """
    if role not in allowed:
        raise err(errors.ERR_FORBIDDEN_ROLE, "Role not permitted for this operation.")


def parse_pagination():
    """Parse limit/offset query params (PRD §2.3).

    limit default 10, min 1, max 100. offset default 0, min 0.
    Out-of-bounds -> ERR_PAGINATION_INVALID (400).
    """
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")

    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (ValueError, TypeError):
            raise err(errors.ERR_PAGINATION_INVALID, "limit must be an integer.")
        if limit < 1 or limit > 100:
            raise err(errors.ERR_PAGINATION_INVALID, "limit out of bounds (1..100).")

    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (ValueError, TypeError):
            raise err(errors.ERR_PAGINATION_INVALID, "offset must be an integer.")
        if offset < 0:
            raise err(errors.ERR_PAGINATION_INVALID, "offset out of bounds (>=0).")

    return limit, offset


def paginate(items, limit, offset):
    """Sort by created_at ascending (PRD §2.3) and apply the window."""
    ordered = sorted(items, key=lambda r: (r["created_at"], r["_seq"]))
    total = len(ordered)
    window = ordered[offset:offset + limit]
    return window, total
