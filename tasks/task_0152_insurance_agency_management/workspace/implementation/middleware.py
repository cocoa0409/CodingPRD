"""Auth (PRD §2.1), RBAC, OCC (§2.9), pagination (§2.3), and lookup helpers.

Validation ordering (§2.10): auth (401) -> authz (403) -> existence (404) ->
well-formedness (400) -> state (409) -> OCC version (412) -> business rules.
The route bodies enforce that ordering by calling these helpers in sequence.
"""
from flask import request

from errors import (
    err,
    ERR_UNAUTHENTICATED,
    ERR_UNAUTHORIZED,
    ERR_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_STALE_VERSION,
)

ROLES = {"AgencyAdmin", "Producer", "AccountManager", "TrustAccountant"}


def authenticate():
    """Validate X-User-Role / X-User-ID presence and role validity (§2.1).

    Returns (user_id, role). Raises ERR_UNAUTHENTICATED (401) if either header
    is missing/empty or the role is not one of the four known roles.
    """
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if not role or not user_id:
        raise err(ERR_UNAUTHENTICATED, "missing X-User-Role or X-User-ID header")
    if role not in ROLES:
        raise err(ERR_UNAUTHENTICATED, "X-User-Role is not a recognized role")
    return user_id, role


def authorize(role, allowed_roles):
    """RBAC check (§2.1). Raises ERR_UNAUTHORIZED (403) if role not permitted."""
    if role not in allowed_roles:
        raise err(ERR_UNAUTHORIZED, f"role {role} may not perform this operation")


def auth(allowed_roles):
    """Combined authenticate + authorize. Returns (user_id, role)."""
    user_id, role = authenticate()
    authorize(role, allowed_roles)
    return user_id, role


def get_json_body():
    """Parse the JSON body, defaulting to {}. Malformed JSON -> 400."""
    if not request.data:
        return {}
    body = request.get_json(silent=True)
    if body is None:
        raise err(ERR_INVALID_REQUEST, "request body must be valid JSON")
    if not isinstance(body, dict):
        raise err(ERR_INVALID_REQUEST, "request body must be a JSON object")
    return body


def lookup(collection, rid):
    """Existence check (§2.5). Raises ERR_NOT_FOUND (404) if id absent."""
    rec = collection.get(rid)
    if rec is None:
        raise err(ERR_NOT_FOUND, "referenced resource does not exist")
    return rec


def check_version(rec, expected, field_name):
    """OCC check (§2.9). expected is required (non-optional) where it applies.

    Raises ERR_INVALID_REQUEST if missing/not-int, ERR_STALE_VERSION (412) if
    it does not equal the record's current version.
    """
    if expected is None:
        raise err(ERR_INVALID_REQUEST, f"missing required field: {field_name}")
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise err(ERR_INVALID_REQUEST, f"{field_name} must be an integer")
    if expected != rec.get("version"):
        raise err(ERR_STALE_VERSION, "version does not match current resource version")


def pagination():
    """Parse limit/offset query params (§2.3).

    limit default 10, min 1, max 100; offset default 0, min 0. Out-of-range or
    non-integer values -> ERR_INVALID_REQUEST (400).
    """
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit = 10
    offset = 0
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except ValueError:
            raise err(ERR_INVALID_REQUEST, "limit must be an integer")
        if limit < 1 or limit > 100:
            raise err(ERR_INVALID_REQUEST, "limit must be between 1 and 100")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except ValueError:
            raise err(ERR_INVALID_REQUEST, "offset must be an integer")
        if offset < 0:
            raise err(ERR_INVALID_REQUEST, "offset must be >= 0")
    return limit, offset


def paginate(records):
    """Sort by created order (oldest first) and slice the current page.

    Returns (page_items, limit, offset, total_count). Sort key is the monotonic
    _seq, which tracks creation order and is consistent with created_at asc.
    """
    limit, offset = pagination()
    ordered = sorted(records, key=lambda r: r.get("_seq", 0))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return page, limit, offset, total
