"""Auth (PRD §2.1) and pagination parsing (PRD §2.3).

Headers (PRD §2.1):
  X-User-ID   — acting user id. For Member it is the acting Applicant.id.
  X-User-Role — one of {PlatformAdmin, FleetOperator, BillingAdmin, Member}.
"""
from flask import request

import errors

KNOWN_ROLES = {"PlatformAdmin", "FleetOperator", "BillingAdmin", "Member"}


def get_identity():
    """Validate auth headers (priority 1, ERR_UNAUTHENTICATED). Returns (user_id, role)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in KNOWN_ROLES:
        raise errors.unauthenticated()
    return user_id, role


def require_roles(role, allowed):
    """Priority 2: role authorization (ERR_FORBIDDEN_ROLE)."""
    if role not in allowed:
        raise errors.forbidden_role()


def parse_pagination():
    """PRD §2.3: limit default 10 (1..100), offset default 0 (>=0).
    Out-of-bounds -> ERR_INVALID_PAGINATION."""
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args and args.get("limit") != "":
        raw = args.get("limit")
        try:
            limit = int(raw)
        except (TypeError, ValueError):
            raise errors.invalid_pagination()
        if limit < 1 or limit > 100:
            raise errors.invalid_pagination()
    if "offset" in args and args.get("offset") != "":
        raw = args.get("offset")
        try:
            offset = int(raw)
        except (TypeError, ValueError):
            raise errors.invalid_pagination()
        if offset < 0:
            raise errors.invalid_pagination()
    return limit, offset
