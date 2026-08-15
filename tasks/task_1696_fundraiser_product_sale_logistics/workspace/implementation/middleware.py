"""Auth header extraction, role checking, body parsing, pagination parsing."""

from flask import request

import errors

ROLES = {"FundraiserAdmin", "GroupCoordinator", "Treasurer", "SupplierRep"}


def actor():
    """Validate X-User-ID / X-User-Role headers. Returns (user_id, role)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise errors.err_unauthenticated()
    return user_id, role


def require_role(*allowed):
    user_id, role = actor()
    if role not in allowed:
        raise errors.err_unauthorized_role()
    return user_id, role


def any_role():
    return require_role("FundraiserAdmin", "GroupCoordinator", "Treasurer", "SupplierRep")


def get_body(required=False):
    """Parse the JSON request body; tolerate empty bodies on action endpoints."""
    if not request.data:
        if required:
            raise errors.err_validation("Request body required")
        return {}
    try:
        body = request.get_json(force=False, silent=False)
    except Exception:
        raise errors.err_validation("Malformed JSON body")
    if body is None:
        if required:
            raise errors.err_validation("Request body required")
        return {}
    if not isinstance(body, dict):
        raise errors.err_validation("Request body must be a JSON object")
    return body


def parse_pagination():
    """Parse limit/offset query params per PRD §2.3 (default 10, min 1, max 100)."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise errors.err_validation("limit must be an integer")
        if limit < 1 or limit > 100:
            raise errors.err_validation("limit must be between 1 and 100")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise errors.err_validation("offset must be an integer")
        if offset < 0:
            raise errors.err_validation("offset must be >= 0")
    return limit, offset
