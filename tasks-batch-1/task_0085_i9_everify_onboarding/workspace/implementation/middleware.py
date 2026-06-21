"""Auth header extraction, RBAC, pagination parsing.

PRD §2.1: every request carries X-User-ID and X-User-Role. The three known roles
are spelled exactly: HRReviewer, EVerifyOperator, ComplianceOfficer. On mutating
endpoints a missing header or unknown role => ERR_UNAUTHENTICATED (401). Reads
are permissive: any of the three known roles may read. A known-but-not-permitted
role => ERR_FORBIDDEN_ROLE (403).
"""

from flask import request

from errors import err

KNOWN_ROLES = {"HRReviewer", "EVerifyOperator", "ComplianceOfficer"}


def get_identity():
    """Return (user_id, role) from headers without validating them."""
    return request.headers.get("X-User-ID"), request.headers.get("X-User-Role")


def authenticate():
    """Validation priority 1 (ERR_UNAUTHENTICATED, 401).

    Both headers present and role is a known role. Used by mutating endpoints.
    For reads we still require a known role to be present (PRD §2.1: 'any of the
    three known roles may read').
    """
    user_id, role = get_identity()
    if not user_id or not role or role not in KNOWN_ROLES:
        raise err("ERR_UNAUTHENTICATED",
                  "Missing or unknown X-User-ID / X-User-Role")
    return user_id, role


def require_roles(allowed_roles):
    """Authenticate, then enforce the RBAC matrix (priority 2,
    ERR_FORBIDDEN_ROLE, 403). Returns (user_id, role)."""
    user_id, role = authenticate()
    if role not in allowed_roles:
        raise err("ERR_FORBIDDEN_ROLE",
                  "Role %s is not permitted for this operation" % role)
    return user_id, role


def require_read_role():
    """Reads: any known role. Still rejects unknown/missing role as
    ERR_UNAUTHENTICATED so a caller with a bogus role does not read."""
    return authenticate()


def parse_pagination():
    """Parse limit/offset query params (PRD §2.3).

    limit defaults 10, min 1, max 100. offset defaults 0, min 0. Out of bounds =>
    ERR_VALIDATION_PAGINATION (400). Non-integer => ERR_VALIDATION_PAGINATION.
    """
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")

    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise err("ERR_VALIDATION_PAGINATION", "limit must be an integer")
        if limit < 1 or limit > 100:
            raise err("ERR_VALIDATION_PAGINATION", "limit out of bounds [1,100]")

    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise err("ERR_VALIDATION_PAGINATION", "offset must be an integer")
        if offset < 0:
            raise err("ERR_VALIDATION_PAGINATION", "offset must be >= 0")

    return limit, offset
