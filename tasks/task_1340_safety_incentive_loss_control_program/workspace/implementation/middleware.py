"""Auth (PRD section 2.1) and pagination (PRD section 2.3) helpers."""

from flask import request

from errors import ApiError

ROLES = ("EHSAdmin", "SafetyManager", "Supervisor", "Employee",
         "CommitteeChair", "ContractorRep", "CarrierConsultant")
ALL_ROLES = list(ROLES)
# Every role except the contractor representative.
NON_CONTRACTOR_ROLES = [r for r in ROLES if r != "ContractorRep"]
# EMR forecast readers: everyone except Employee and ContractorRep.
FORECAST_READ_ROLES = ["EHSAdmin", "SafetyManager", "Supervisor",
                       "CommitteeChair", "CarrierConsultant"]


def auth(allowed=None):
    """Validate X-User-ID / X-User-Role; optionally enforce endpoint roles.

    Returns (user_id, role). For entity-backed roles the identity header is the
    id of the acting Employee (or ContractorOrg for ContractorRep); ownership
    checks compare the recorded FK directly against X-User-ID (PRD 2.1).
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", 401,
                       "Missing or invalid X-User-ID / X-User-Role headers")
    if allowed is not None and role not in allowed:
        raise ApiError("ERR_UNAUTHORIZED", 403,
                       "Role not permitted for this endpoint")
    return user_id, role


def parse_limit_offset():
    """Read limit/offset with the PRD defaults (limit 10, min 1, max 100; offset 0)."""
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    try:
        limit = int(limit_raw) if limit_raw is not None else 10
        offset = int(offset_raw) if offset_raw is not None else 0
    except (TypeError, ValueError):
        raise ApiError("ERR_INVALID_REQUEST", 400, "Invalid limit/offset")
    if isinstance(limit, bool) or isinstance(offset, bool) \
            or limit < 1 or limit > 100 or offset < 0:
        raise ApiError("ERR_INVALID_REQUEST", 400, "Invalid limit/offset")
    return limit, offset


def paginate(items):
    """Apply limit/offset; return (page_items, total_count, limit, offset)."""
    limit, offset = parse_limit_offset()
    total = len(items)
    return items[offset:offset + limit], total, limit, offset
