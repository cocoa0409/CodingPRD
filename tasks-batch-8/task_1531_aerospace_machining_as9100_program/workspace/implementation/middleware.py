"""Auth header extraction and role gating (PRD §2.1, validation priorities 1-2)."""

from flask import request

from errors import (
    ApiError,
    ERR_INSUFFICIENT_PERMISSIONS,
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
)

ALL_ROLES = [
    "ContractsManager",
    "SupplyChainManager",
    "ManufacturingPlanner",
    "QualityInspector",
    "MRBMember",
    "QualityManager",
    "CustomerQualityRep",
    "SystemAdmin",
]


def require_roles(*allowed):
    """Validate X-User-ID / X-User-Role and gate on the allowed role set.

    Returns the caller's X-User-ID.
    """
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if uid is None or role is None or uid.strip() == "" or role.strip() == "":
        raise ApiError(
            ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            400,
            "X-User-ID and X-User-Role headers must be present and non-empty",
        )
    if role not in allowed:
        raise ApiError(
            ERR_INSUFFICIENT_PERMISSIONS,
            403,
            "Role %s is not permitted on this endpoint" % role,
        )
    return uid
