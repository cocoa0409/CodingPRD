"""Auth header extraction, role checking, pagination parsing.

PRD §2.1: Every request must carry X-User-ID and X-User-Role. Missing either
-> ERR_UNAUTHENTICATED (401). Present but role not permitted -> ERR_FORBIDDEN_ROLE (403).
The six roles: Homeowner, Estimator, Inspector, Scheduler, WarrantyAdmin, FinancePartner.
"""
from flask import request

import errors

VALID_ROLES = {
    "Homeowner", "Estimator", "Inspector", "Scheduler", "WarrantyAdmin", "FinancePartner",
}


def authenticate():
    """Validate presence of auth headers. Returns (user_id, role). PRD §2.7: auth first."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role:
        raise errors.err(errors.ERR_UNAUTHENTICATED, "Missing X-User-ID or X-User-Role header")
    return user_id, role


def authorize(role, allowed_roles):
    """PRD §2.7: authorization comes right after authentication."""
    if role not in allowed_roles:
        raise errors.err(errors.ERR_FORBIDDEN_ROLE, "Role %s is not permitted for this operation" % role)


def get_pagination():
    """Parse limit/offset query params per PRD §2.3.

    limit defaults to 10, min 1, max 100. offset defaults to 0, min 0.
    Out of bounds -> ERR_PAGINATION_INVALID (400).
    """
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")

    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (ValueError, TypeError):
            raise errors.err(errors.ERR_PAGINATION_INVALID, "limit must be an integer")
        if limit < 1 or limit > 100:
            raise errors.err(errors.ERR_PAGINATION_INVALID, "limit must be between 1 and 100")

    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (ValueError, TypeError):
            raise errors.err(errors.ERR_PAGINATION_INVALID, "offset must be an integer")
        if offset < 0:
            raise errors.err(errors.ERR_PAGINATION_INVALID, "offset must be >= 0")

    return limit, offset


def get_json_body():
    """Return the parsed JSON body as a dict (empty dict if none)."""
    if not request.data:
        return {}
    try:
        body = request.get_json(force=True, silent=True)
    except Exception:
        body = None
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise errors.err(errors.ERR_INVALID_REQUEST, "Request body must be a JSON object")
    return body
