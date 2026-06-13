"""Auth header extraction, role checking, and common request helpers.

Auth headers (PRD §2.1): X-User-ID and X-User-Role. Roles recognized:
DistributorAdmin, SalesRep, WarehouseOp, CreditManager. Identity is opaque
for all roles — X-User-ID is never matched against a stored FK.
"""
from flask import request

import db
import errors

VALID_ROLES = {"DistributorAdmin", "SalesRep", "WarehouseOp", "CreditManager"}


def require_auth():
    """Validate that X-User-ID and X-User-Role are present and well-formed.

    Returns (user_id, role). Raises ERR_MISSING_USER_CONTEXT (401) on a missing
    or malformed header. A malformed role value (not one of the four recognized
    roles) is treated as malformed user context.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not isinstance(user_id, str) or user_id.strip() == "":
        raise errors.missing_user_context()
    if not role or role not in VALID_ROLES:
        raise errors.missing_user_context()
    return user_id, role


def require_role(role, allowed):
    """Raise ERR_FORBIDDEN_FOR_ROLE (403) if role not in allowed set."""
    if role not in allowed:
        raise errors.forbidden_for_role()


def get_json_body():
    """Return the parsed JSON body as a dict, or {} when absent.

    A body that is present but not a JSON object is malformed.
    """
    if request.data is None or len(request.data) == 0:
        return {}
    try:
        body = request.get_json(force=True, silent=True)
    except Exception:
        raise errors.invalid_request("Request body is not valid JSON.")
    if body is None:
        # Could not parse a non-empty body.
        return {}
    if not isinstance(body, dict):
        raise errors.invalid_request("Request body must be a JSON object.")
    return body


def parse_pagination():
    """Parse limit/offset query params per PRD §2.3.

    limit default 10, min 1, max 100. offset default 0, min 0. Out-of-range or
    non-integer values raise ERR_VALIDATION_LIMIT (422).
    """
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")

    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (ValueError, TypeError):
            raise errors.validation_limit()
        if limit < 1 or limit > 100:
            raise errors.validation_limit()

    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (ValueError, TypeError):
            raise errors.validation_limit()
        if offset < 0:
            raise errors.validation_limit()

    return limit, offset


def paginate(items):
    """Apply pagination to an already-sorted list. Returns (page, meta dict)."""
    limit, offset = parse_pagination()
    total = len(items)
    page = items[offset:offset + limit]
    has_more = (offset + limit) < total
    return page, limit, offset, total, has_more
