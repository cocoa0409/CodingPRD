"""Auth + RBAC + request parsing helpers.

PRD §2.1: every request carries X-User-ID and X-User-Role (both mandatory,
non-empty). Roles: Technician, QualityEngineer, Metrologist.

Validation ordering (PRD §2.10):
  1. ERR_MISSING_USER_CONTEXT (401) — headers present & non-empty
  2. ERR_FORBIDDEN_ROLE (403) — role known AND permitted for this operation
  3. ERR_NOT_FOUND (404) — path ids left-to-right
  4. ERR_FK_NOT_FOUND (404) — body FKs
  5. ERR_INVALID_REQUEST (422) — required fields/types/enums/ranges
  ... then uniqueness, state, business safety
"""
from flask import request

from errors import err

ROLES = {"Technician", "QualityEngineer", "Metrologist"}


def require_auth(allowed_roles):
    """Check auth headers + role permission. Returns (user_id, role).

    `allowed_roles` is an iterable of role names permitted for the operation.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role:
        raise err("ERR_MISSING_USER_CONTEXT",
                  "X-User-ID and X-User-Role headers are required")
    if role not in ROLES or role not in allowed_roles:
        raise err("ERR_FORBIDDEN_ROLE",
                  "Role '%s' is not permitted for this operation" % role)
    return user_id, role


def get_json():
    """Parse the JSON body; tolerate empty/absent body as {}."""
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise err("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    return data


def get_pagination():
    """Read limit/offset per PRD §2.3.

    limit default 10, min 1, max 100; offset default 0. Invalid values raise
    ERR_INVALID_REQUEST (422).
    """
    args = request.args
    limit = args.get("limit")
    offset = args.get("offset")

    if limit is None:
        limit_v = 10
    else:
        try:
            limit_v = int(limit)
        except (ValueError, TypeError):
            raise err("ERR_INVALID_REQUEST", "limit must be an integer")
        if limit_v < 1 or limit_v > 100:
            raise err("ERR_INVALID_REQUEST", "limit must be between 1 and 100")

    if offset is None:
        offset_v = 0
    else:
        try:
            offset_v = int(offset)
        except (ValueError, TypeError):
            raise err("ERR_INVALID_REQUEST", "offset must be an integer")
        if offset_v < 0:
            raise err("ERR_INVALID_REQUEST", "offset must be >= 0")

    return limit_v, offset_v
