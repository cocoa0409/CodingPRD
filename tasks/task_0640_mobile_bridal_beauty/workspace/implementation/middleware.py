"""Auth header extraction, role checking, pagination parsing (PRD §2.1, §2.3, §2.9)."""
from flask import request

import errors

VALID_ROLES = {"Coordinator", "Artist", "Client"}


def get_identity():
    """Validate the two mandatory headers (PRD §2.1). Returns (user_id, role).

    Missing or malformed either header -> ERR_UNAUTHENTICATED (401).
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or role is None:
        raise errors.unauthenticated()
    user_id = user_id.strip()
    role = role.strip()
    if not user_id or not role:
        raise errors.unauthenticated()
    if role not in VALID_ROLES:
        # Malformed role value: not one of the recognized roles.
        raise errors.unauthenticated()
    return user_id, role


def require_role(role, allowed):
    """Role-authorization check (PRD §2.9). Raises ERR_FORBIDDEN_ROLE (403)."""
    if role not in allowed:
        raise errors.forbidden_role()


def parse_pagination():
    """Parse limit/offset (PRD §2.3). Defaults limit=10 [1,100], offset=0.

    A malformed pagination value surfaces as ERR_INVALID_REQUEST (400).
    """
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")

    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (ValueError, TypeError):
            raise errors.invalid_request("limit must be an integer")
        if limit < 1 or limit > 100:
            raise errors.invalid_request("limit out of range [1,100]")

    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (ValueError, TypeError):
            raise errors.invalid_request("offset must be an integer")
        if offset < 0:
            raise errors.invalid_request("offset must be >= 0")

    return limit, offset


def get_json_body():
    """Return the request JSON body as a dict, or {} when absent.

    A body that is present but not a JSON object surfaces as ERR_INVALID_REQUEST.
    """
    if not request.data:
        return {}
    try:
        data = request.get_json(force=True, silent=False)
    except Exception:
        raise errors.invalid_request("Malformed JSON body")
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise errors.invalid_request("Request body must be a JSON object")
    return data
