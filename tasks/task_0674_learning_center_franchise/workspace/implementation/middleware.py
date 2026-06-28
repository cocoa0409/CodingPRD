"""Auth header extraction, RBAC, pagination parsing (PRD §2.1, §2.3, §2.8).

Auth headers: X-User-ID and X-User-Role. Roles: FranchiseAdmin, CenterDirector,
Instructor, Parent. Missing/unknown -> ERR_UNAUTHENTICATED (401).
"""
from flask import request

import errors

ROLES = {"FranchiseAdmin", "CenterDirector", "Instructor", "Parent"}


def get_auth():
    """Validate auth headers (priority 1). Returns (user_id, role)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise errors.unauthenticated()
    return user_id, role


def require_role(role, allowed):
    """RBAC role gate (priority 2). allowed is an iterable of role names."""
    if role not in allowed:
        raise errors.forbidden()


def parse_pagination():
    """limit (default 10, min 1, max 100), offset (default 0).

    Out-of-range/non-integer values -> ERR_INVALID_REQUEST (422).
    """
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args:
        raw = args.get("limit")
        try:
            limit = int(raw)
        except (TypeError, ValueError):
            raise errors.invalid_request("limit must be an integer.")
        if limit < 1 or limit > 100:
            raise errors.invalid_request("limit must be between 1 and 100.")
    if "offset" in args:
        raw = args.get("offset")
        try:
            offset = int(raw)
        except (TypeError, ValueError):
            raise errors.invalid_request("offset must be an integer.")
        if offset < 0:
            raise errors.invalid_request("offset must be >= 0.")
    return limit, offset


def get_body():
    """Return the JSON body as a dict, or {} when absent. Malformed -> 422."""
    if not request.data:
        return {}
    try:
        body = request.get_json(force=True, silent=True)
    except Exception:
        raise errors.invalid_request("Request body is not valid JSON.")
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise errors.invalid_request("Request body must be a JSON object.")
    return body
