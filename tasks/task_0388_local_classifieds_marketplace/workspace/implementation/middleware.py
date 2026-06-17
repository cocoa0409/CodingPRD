"""Auth header extraction, RBAC, and request parsing helpers.

Auth headers (PRD §2.1): X-User-ID and X-User-Role.
Validation order (PRD §2.8): auth(401) -> role(403) -> owner(403) -> ...
"""
from flask import request

import constants as C
from errors import err


def auth_context(require_auth=True):
    """Return (user_id, role). Enforces presence/well-formedness of the two
    headers when require_auth is True (ERR_UNAUTHENTICATED on failure).

    For public reads (require_auth=False) missing headers are tolerated and the
    caller is treated as Anonymous; but if a role header IS present it must be a
    recognized role value.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")

    if require_auth:
        if not user_id or not role or role not in C.ALL_ROLES:
            raise err("ERR_UNAUTHENTICATED", "Missing or malformed authentication headers.")
        return user_id, role

    # Public read: allow fully anonymous (no headers). If a role is supplied it
    # must be well-formed; otherwise reject as unauthenticated.
    if role is None and user_id is None:
        return None, C.ROLE_ANONYMOUS
    if not user_id or not role or role not in C.ALL_ROLES:
        raise err("ERR_UNAUTHENTICATED", "Missing or malformed authentication headers.")
    return user_id, role


def require_role(role, allowed):
    """Priority 2 (PRD §2.8): the acting role must be among the endpoint's
    authorized roles, else ERR_FORBIDDEN_ROLE."""
    if role not in allowed:
        raise err("ERR_FORBIDDEN_ROLE", "Role not authorized for this endpoint.")


def parse_pagination(args):
    """Parse limit/offset query params (PRD §2.3). limit default 10, min 1,
    max 100; offset default 0. Out-of-range/bad values -> ERR_INVALID_REQUEST."""
    limit = C.PAGINATION_DEFAULT_LIMIT
    offset = C.PAGINATION_DEFAULT_OFFSET

    if "limit" in args and args.get("limit") != "":
        raw = args.get("limit")
        try:
            limit = int(raw)
        except (TypeError, ValueError):
            raise err("ERR_INVALID_REQUEST", "limit must be an integer.")
        if limit < C.PAGINATION_MIN_LIMIT or limit > C.PAGINATION_MAX_LIMIT:
            raise err("ERR_INVALID_REQUEST", "limit out of range.")

    if "offset" in args and args.get("offset") != "":
        raw = args.get("offset")
        try:
            offset = int(raw)
        except (TypeError, ValueError):
            raise err("ERR_INVALID_REQUEST", "offset must be an integer.")
        if offset < 0:
            raise err("ERR_INVALID_REQUEST", "offset must be >= 0.")

    return limit, offset


def get_json_body():
    """Return the parsed JSON body as a dict (empty dict when no body).
    Malformed JSON -> ERR_INVALID_REQUEST."""
    if not request.data:
        return {}
    try:
        body = request.get_json(force=True, silent=False)
    except Exception:
        raise err("ERR_INVALID_REQUEST", "Malformed JSON body.")
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise err("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return body
