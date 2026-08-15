"""Auth middleware: X-User-ID / X-User-Role header extraction and role checking."""

from flask import request

import errors

DECLARED_ROLES = {"Participant", "PlanSponsor", "RecordkeeperAdmin", "PayrollProvider", "Auditor"}

# Header names (per PRD section 2.1)
HDR_USER_ID = "X-User-ID"
HDR_USER_ROLE = "X-User-Role"


def get_auth():
    """Return (user_id, role) or raise ERR_UNAUTHENTICATED."""
    user_id = request.headers.get(HDR_USER_ID)
    role = request.headers.get(HDR_USER_ROLE)
    if not user_id or not role or role not in DECLARED_ROLES:
        raise errors.err(errors.ERR_UNAUTHENTICATED,
                         "Missing or unrecognized X-User-Role / X-User-ID headers", 401)
    return user_id, role


def require_roles(*allowed_roles):
    """Authenticate and enforce that the caller's role is in allowed_roles."""
    user_id, role = get_auth()
    if role not in allowed_roles:
        raise errors.err(errors.ERR_UNAUTHORIZED_ROLE,
                         f"Role {role} is not permitted for this endpoint", 403)
    return user_id, role


def check_participant_ownership(user_id, role, participant_id):
    """When role is Participant, X-User-ID must equal the participant id."""
    if role == "Participant" and user_id != participant_id:
        raise errors.err(errors.ERR_UNAUTHORIZED_ROLE,
                         "Participant may act only on its own resources", 403)


def parse_limit_offset():
    """Read limit/offset query params with the scaffold's defaults/min/max."""
    try:
        limit_raw = request.args.get("limit")
        offset_raw = request.args.get("offset")
        limit = int(limit_raw) if limit_raw is not None else 10
        offset = int(offset_raw) if offset_raw is not None else 0
    except (TypeError, ValueError):
        raise errors.err(errors.ERR_INVALID_REQUEST, "Invalid limit/offset", 400)
    if limit < 1 or limit > 100 or offset < 0:
        raise errors.err(errors.ERR_INVALID_REQUEST, "Invalid limit/offset", 400)
    return limit, offset


def paginate(items):
    """Apply limit/offset and return (page_items, total_count, limit, offset)."""
    limit, offset = parse_limit_offset()
    total = len(items)
    page = items[offset:offset + limit]
    return page, total, limit, offset
