"""Auth header extraction, role checking, pagination parsing, body helpers."""

from flask import request

import errors

ROLES = {"TrustAdmin", "EmployerRep", "CommitteeMember", "Instructor"}


def get_auth():
    """Validate X-User-ID / X-User-Role headers. Returns (user_id, role)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not isinstance(user_id, str) or user_id.strip() == "":
        raise errors.err_missing_context()
    if not role or role not in ROLES:
        raise errors.err_missing_context()
    return user_id, role


def require_roles(*allowed):
    """Validate headers, then role permission. Returns (user_id, role)."""
    user_id, role = get_auth()
    if role not in allowed:
        raise errors.err_forbidden_role()
    return user_id, role


def get_body():
    """Return the JSON request body as a dict, or {} for empty bodies.

    A present-but-non-object body (array, scalar) is an invalid request.
    """
    if not request.data:
        return {}
    try:
        body = request.get_json(force=True, silent=False)
    except Exception:
        raise errors.err_invalid_request("Request body must be valid JSON")
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise errors.err_invalid_request("Request body must be a JSON object")
    return body


def require_fields(body, fields):
    """Check required fields are present (not None)."""
    for f in fields:
        if f not in body or body[f] is None:
            raise errors.err_invalid_request(f"Missing required field: {f}")


def parse_pagination(args):
    """Parse limit/offset query params per scaffold pagination defaults.

    limit: default 10, min 1, max 100. offset: default 0, min 0.
    Non-integer or out-of-range values are ERR_INVALID_REQUEST.
    """
    raw_limit = args.get("limit")
    raw_offset = args.get("offset")

    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise errors.err_invalid_request("limit must be an integer")
        if limit < 1 or limit > 100:
            raise errors.err_invalid_request("limit must be between 1 and 100")

    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise errors.err_invalid_request("offset must be an integer")
        if offset < 0:
            raise errors.err_invalid_request("offset must be >= 0")

    return limit, offset


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def is_num(v):
    return (isinstance(v, (int, float)) and not isinstance(v, bool))


def is_str(v):
    return isinstance(v, str)
