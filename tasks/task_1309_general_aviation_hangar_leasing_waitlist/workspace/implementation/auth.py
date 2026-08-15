"""Auth context extraction and role/ownership checks (PRD section 2.1).

Headers: X-User-ID and X-User-Role. Roles: AirportManager, ComplianceOfficer,
Applicant, Tenant. Applicant identity is the WaitlistApplication id; Tenant
identity is the Lease id; manager/officer ids are opaque."""
from flask import request

from errors import (
    ApiError,
    ERR_INSUFFICIENT_PERMISSIONS,
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
)

ROLES = ("AirportManager", "ComplianceOfficer", "Applicant", "Tenant")
ALL_ROLES = ROLES


def get_context():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if uid is None or not uid.strip():
        raise ApiError(
            ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            "X-User-ID header missing or malformed",
            400,
        )
    if role is None or role not in ROLES:
        raise ApiError(
            ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            "X-User-Role header missing or malformed",
            400,
        )
    return uid, role


def require_roles(*roles):
    """Priority 1-2 of the validation pipeline: headers then role authorization."""
    uid, role = get_context()
    if role not in roles:
        raise ApiError(
            ERR_INSUFFICIENT_PERMISSIONS,
            "Role %s is not permitted for this endpoint" % role,
            403,
        )
    return uid, role


def require_ownership(owner_id, uid):
    """Entity-backed identity check: the resource's FK must equal X-User-ID."""
    if owner_id != uid:
        raise ApiError(
            ERR_INSUFFICIENT_PERMISSIONS,
            "Caller does not own the target resource",
            403,
        )
