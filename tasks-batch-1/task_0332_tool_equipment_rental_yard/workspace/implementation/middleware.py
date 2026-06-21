"""Auth header extraction, role checking, and pagination parsing.

PRD §2.1: write endpoints require X-User-ID and X-User-Role. GET reads are
public. The four recognized roles are YardManager, RentalAgent, Contractor,
Inspector.
PRD §2.3: pagination via limit/offset query params.
"""
from flask import request

import errors

VALID_ROLES = {"YardManager", "RentalAgent", "Contractor", "Inspector"}


def get_identity():
    """Return (user_id, role) from headers, or (None, None) if absent."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    return user_id, role


def require_auth(allowed_roles):
    """Validate auth headers and role membership for a write endpoint.

    PRD §2.1 priority order:
      1. ERR_UNAUTHENTICATED (401) when either header missing/malformed or the
         role is not one of the four recognized roles.
      2. ERR_UNAUTHORIZED (403) when the role is valid but not permitted for the
         operation per the role matrix.

    Returns (user_id, role).
    """
    user_id, role = get_identity()
    # Both headers must be present and non-empty, and role must be recognized.
    if not user_id or not role or role not in VALID_ROLES:
        raise errors.unauthenticated()
    if role not in allowed_roles:
        raise errors.unauthorized()
    return user_id, role


def parse_pagination():
    """Parse limit/offset query params per PRD §2.3.

    limit default 10, min 1, max 100; offset default 0, may not be negative.
    Out-of-bounds -> ERR_VALIDATION_LIMIT (400).
    """
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")

    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise errors.validation_limit()
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise errors.validation_limit()

    if limit < 1 or limit > 100 or offset < 0:
        raise errors.validation_limit()
    return limit, offset
