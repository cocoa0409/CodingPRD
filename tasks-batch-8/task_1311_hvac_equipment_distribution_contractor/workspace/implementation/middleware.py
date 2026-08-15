"""Auth header extraction, role checking, ownership, and pagination parsing."""
from flask import request

from errors import ApiError, ERR_UNAUTHENTICATED, ERR_UNAUTHORIZED

ROLES = {
    "DistributorAdmin",
    "ContractorUser",
    "WarrantyProcessor",
    "ComplianceOfficer",
    "TrainingCoordinator",
}


def authenticate():
    """Stage 1: X-User-ID and X-User-Role present, role declared."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise ApiError(ERR_UNAUTHENTICATED, 401,
                       "Missing or invalid X-User-ID / X-User-Role headers")
    return user_id, role


def authorize(allowed_roles, role):
    """Stage 2: role permitted for the endpoint."""
    if role not in allowed_roles:
        raise ApiError(ERR_UNAUTHORIZED, 403,
                       "Role %s is not permitted for this endpoint" % role)


def require_owner(resource_contractor_id, role, user_id):
    """Ownership: a ContractorUser may only touch resources whose contractor
    foreign key equals their X-User-ID."""
    if role == "ContractorUser" and resource_contractor_id != user_id:
        raise ApiError(ERR_UNAUTHORIZED, 403,
                       "ContractorUser may only access their own resources")


def pagination_params():
    """limit/offset per PRD 2.3: default 10/0, min 1, max 100 (clamped)."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit, offset = 10, 0
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", 400,
                           "limit must be an integer")
        limit = max(1, min(100, limit))
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", 400,
                           "offset must be an integer")
        offset = max(0, offset)
    return limit, offset
