"""Auth header extraction, role checking, and pagination parsing.

Auth headers (PRD §2.1): X-User-ID and X-User-Role, both mandatory.
Valid roles: ClinicAdmin, Clinician, Collector, MRO.
"""

from flask import request

import errors
from errors import err

VALID_ROLES = {"ClinicAdmin", "Clinician", "Collector", "MRO"}


class Caller:
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role


def authenticate():
    """Validate auth headers (priority 1). Returns a Caller or raises 401."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not isinstance(user_id, str) or not user_id.strip():
        raise err(errors.ERR_MISSING_OR_INVALID_USER_CONTEXT,
                  "X-User-ID header missing or malformed")
    if not role or role not in VALID_ROLES:
        raise err(errors.ERR_MISSING_OR_INVALID_USER_CONTEXT,
                  "X-User-Role header missing or malformed")
    return Caller(user_id, role)


def require_role(caller, allowed_roles):
    """Role authorization (priority 2). Raises 403 if caller's role not allowed."""
    if caller.role not in allowed_roles:
        raise err(errors.ERR_INSUFFICIENT_PERMISSIONS,
                  "Role %s is not permitted for this operation" % caller.role)


def parse_pagination():
    """Parse limit/offset query params per PRD §2.3.

    limit default 10, min 1, max 100; offset default 0. Out-of-range / malformed
    values are treated as ERR_INVALID_REQUEST? No — the PRD does not declare an
    error for bad pagination, so we clamp/default gracefully.
    """
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")

    limit = 10
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            limit = 10
        if limit < 1:
            limit = 1
        elif limit > 100:
            limit = 100

    offset = 0
    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            offset = 0
        if offset < 0:
            offset = 0

    return limit, offset
