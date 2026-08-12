"""Auth header extraction, role authorization, and ownership checks.

Pipeline stages 2 (authentication), 3 (role authorization), 5 (ownership).
"""
from flask import request

import db
from errors import (
    ERR_FORBIDDEN_OWNERSHIP,
    ERR_FORBIDDEN_ROLE,
    ERR_NOT_FOUND,
    ERR_UNAUTHENTICATED,
    ApiError,
)

ROLES = {
    "SystemAdmin",
    "DistrictAdmin",
    "ContractorOps",
    "HRRecruiter",
    "FleetManager",
    "FinanceClerk",
    "Driver",
}


def authenticate():
    """Stage 2: X-User-Role and X-User-ID present, role recognized."""
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if not role or not user_id or role not in ROLES:
        raise ApiError(
            ERR_UNAUTHENTICATED[0],
            ERR_UNAUTHENTICATED[1],
            "Missing or unrecognized X-User-Role / X-User-ID headers",
        )
    return {"role": role, "user_id": user_id}


def require_roles(actor, allowed):
    """Stage 3: acting role in endpoint's roles list."""
    if actor["role"] not in allowed:
        raise ApiError(
            ERR_FORBIDDEN_ROLE[0],
            ERR_FORBIDDEN_ROLE[1],
            "Role %s is not authorized for this endpoint" % actor["role"],
        )


def get_or_404(store, rec_id, label="Resource"):
    """Stage 4 existence on a single id."""
    rec = db.find(store, rec_id)
    if rec is None:
        raise ApiError(
            ERR_NOT_FOUND[0], ERR_NOT_FOUND[1], "%s %s not found" % (label, rec_id)
        )
    return rec


def body_ref_or_404(body, key, store, label):
    """Stage 4 existence for a required body foreign-key reference."""
    v = body.get(key)
    if v is None:
        raise ApiError(
            ERR_NOT_FOUND[0], ERR_NOT_FOUND[1], "%s %s not found" % (label, v)
        )
    return get_or_404(store, v, label)


def district_ownership(actor, district_id):
    """Stage 5: DistrictAdmin may act only on their own district's resources."""
    if actor["role"] == "DistrictAdmin" and actor["user_id"] != district_id:
        raise ApiError(
            ERR_FORBIDDEN_OWNERSHIP[0],
            ERR_FORBIDDEN_OWNERSHIP[1],
            "DistrictAdmin may act only on resources of their own district",
        )


def driver_ownership(actor, driver_id):
    """Stage 5: Driver may act only on their own assignments / record."""
    if actor["role"] == "Driver" and actor["user_id"] != driver_id:
        raise ApiError(
            ERR_FORBIDDEN_OWNERSHIP[0],
            ERR_FORBIDDEN_OWNERSHIP[1],
            "Driver may act only on their own assignments and record",
        )


def read_scoping(actor, rec):
    """Ownership scoping on single-resource reads (contract/charter/invoice/
    incident for DistrictAdmin; assignments and driver record for Driver).

    Returns an ApiError to raise, or None when the read is allowed.
    """
    role = actor["role"]
    if role == "DistrictAdmin":
        district_id = rec.get("_district_ref")
        if district_id is not None and district_id != actor["user_id"]:
            return ApiError(
                ERR_FORBIDDEN_OWNERSHIP[0],
                ERR_FORBIDDEN_OWNERSHIP[1],
                "DistrictAdmin may act only on resources of their own district",
            )
    if role == "Driver":
        driver_ref = rec.get("_driver_ref")
        if driver_ref is not None and driver_ref != actor["user_id"]:
            return ApiError(
                ERR_FORBIDDEN_OWNERSHIP[0],
                ERR_FORBIDDEN_OWNERSHIP[1],
                "Driver may read only their own record and assignments",
            )
    return None
