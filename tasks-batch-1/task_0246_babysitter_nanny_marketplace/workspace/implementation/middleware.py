"""Auth extraction, role gating, pagination, and body helpers.

Auth headers (PRD §2.1):
  - X-User-Role : one of PlatformAdmin | Family | Caregiver
  - X-User-ID   : acting principal id (entity id for Family/Caregiver,
                  opaque for PlatformAdmin)
"""

from flask import request

import errors
from errors import err

VALID_ROLES = {"PlatformAdmin", "Family", "Caregiver"}


class Auth:
    def __init__(self, role, user_id):
        self.role = role
        self.user_id = user_id

    @property
    def is_admin(self):
        return self.role == "PlatformAdmin"

    @property
    def is_family(self):
        return self.role == "Family"

    @property
    def is_caregiver(self):
        return self.role == "Caregiver"


def authenticate():
    """Validate the two mandatory auth headers. Raises ERR_UNAUTHENTICATED."""
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if not role or not user_id:
        raise err(errors.ERR_UNAUTHENTICATED, "Missing authentication headers")
    if role not in VALID_ROLES:
        raise err(errors.ERR_UNAUTHENTICATED, "Invalid X-User-Role")
    if not isinstance(user_id, str) or user_id.strip() == "":
        raise err(errors.ERR_UNAUTHENTICATED, "Invalid X-User-ID")
    return Auth(role, user_id)


def require_roles(auth, allowed):
    """Role gate (priority 2). Raises ERR_FORBIDDEN if role not permitted."""
    if auth.role not in allowed:
        raise err(errors.ERR_FORBIDDEN, "Role not permitted for this operation")


def get_json():
    """Parse the request JSON body, tolerating an empty body as {}."""
    if not request.data:
        return {}
    data = request.get_json(silent=True)
    if data is None:
        # Body present but unparseable.
        raise err(errors.ERR_VALIDATION, "Malformed JSON body")
    if not isinstance(data, dict):
        raise err(errors.ERR_VALIDATION, "Request body must be a JSON object")
    return data


# --- pagination (PRD §2.3) -------------------------------------------------
def parse_pagination():
    args = request.args
    limit = args.get("limit")
    offset = args.get("offset")

    if limit is None:
        limit_val = 10
    else:
        try:
            limit_val = int(limit)
        except (ValueError, TypeError):
            raise err(errors.ERR_VALIDATION, "limit must be an integer")
        if limit_val < 1 or limit_val > 100:
            raise err(errors.ERR_VALIDATION, "limit out of range (1..100)")

    if offset is None:
        offset_val = 0
    else:
        try:
            offset_val = int(offset)
        except (ValueError, TypeError):
            raise err(errors.ERR_VALIDATION, "offset must be an integer")
        if offset_val < 0:
            raise err(errors.ERR_VALIDATION, "offset must be >= 0")

    return limit_val, offset_val


def paginate(items, limit, offset):
    """Sort already handled by caller. Returns (page, pagination_meta)."""
    total = len(items)
    page = items[offset:offset + limit]
    has_more = (offset + limit) < total
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": has_more,
    }
    return page, meta
