"""Facility endpoints."""
from flask import Blueprint, request

import db
import services as svc
from errors import (
    ApiError, ERR_INVALID_STATE, ERR_ARCHIVE_BLOCKED, ERR_VALIDATION,
    not_found, validation,
)
from middleware import require_roles, check_facility_ownership
from response import success_object

bp = Blueprint("facilities", __name__)

ALL_ROLES = ("DistributorAdmin", "FacilityManager", "SalesRep", "FieldTechnician")


def facility_view(f):
    return dict(f)


@bp.post("/jansan/facilities")
def create_facility():
    user_id, role = require_roles("DistributorAdmin")
    body = request.get_json(silent=True) or {}
    name = svc.as_str(svc.require_field(body, "name"), "name")
    group = svc.as_str(svc.require_field(body, "facility_group_code"), "facility_group_code")
    credit = svc.as_int(svc.require_field(body, "credit_limit_cents"), "credit_limit_cents")
    zone = svc.as_str(svc.require_field(body, "service_zone"), "service_zone")
    miles = svc.as_number(svc.require_field(body, "delivery_distance_miles"), "delivery_distance_miles")
    day = svc.as_str(svc.require_field(body, "default_delivery_day"), "default_delivery_day")

    f = svc.base_resource()
    f.update({
        "name": name,
        "facility_group_code": group,
        "credit_limit_cents": credit,
        "service_zone": zone,
        "delivery_distance_miles": miles,
        "default_delivery_day": day,
        "status": "ACTIVE",
        "committed_cents": 0,
        "outstanding_cents": 0,
        "closed_loop_enrolled": False,
    })
    db.facilities[f["id"]] = f
    return success_object(facility_view(f), 201)


def get_facility_or_404(facility_id):
    f = db.facilities.get(facility_id)
    if f is None:
        raise not_found("Facility not found")
    return f


@bp.get("/jansan/facilities/<facility_id>")
def get_facility(facility_id):
    user_id, role = require_roles(*ALL_ROLES)
    f = get_facility_or_404(facility_id)
    check_facility_ownership(user_id, role, f["id"])
    return success_object(facility_view(f))


@bp.post("/jansan/facilities/<facility_id>/suspend")
def suspend_facility(facility_id):
    require_roles("DistributorAdmin")
    f = get_facility_or_404(facility_id)
    if f["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, "Facility is not ACTIVE", 409)
    f["status"] = "SUSPENDED"
    svc.touch(f)
    # Cascade: ACTIVE standing orders -> PAUSED with pause_reason SUSPENSION
    for so in db.standing_orders.values():
        if so["facility_id"] == f["id"] and so["status"] == "ACTIVE":
            so["status"] = "PAUSED"
            so["pause_reason"] = "SUSPENSION"
            svc.touch(so)
    return success_object(facility_view(f))


@bp.post("/jansan/facilities/<facility_id>/reinstate")
def reinstate_facility(facility_id):
    require_roles("DistributorAdmin")
    f = get_facility_or_404(facility_id)
    if f["status"] != "SUSPENDED":
        raise ApiError(ERR_INVALID_STATE, "Facility is not SUSPENDED", 409)
    f["status"] = "ACTIVE"
    svc.touch(f)
    # Conditional cascade: resume only SUSPENSION-paused
    for so in db.standing_orders.values():
        if (so["facility_id"] == f["id"] and so["status"] == "PAUSED"
                and so["pause_reason"] == "SUSPENSION"):
            so["status"] = "ACTIVE"
            so["pause_reason"] = "NONE"
            svc.touch(so)
    return success_object(facility_view(f))


@bp.post("/jansan/facilities/<facility_id>/archive")
def archive_facility(facility_id):
    require_roles("DistributorAdmin")
    f = get_facility_or_404(facility_id)
    if f["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, "Facility is not ACTIVE", 409)
    for o in db.orders.values():
        if o["facility_id"] == f["id"] and o["status"] in ("DRAFT", "PLACED", "PARTIALLY_BLOCKED", "DELIVERED"):
            raise ApiError(ERR_ARCHIVE_BLOCKED, "Facility has open orders", 409)
    for so in db.standing_orders.values():
        if so["facility_id"] == f["id"] and so["status"] in ("DRAFT", "ACTIVE", "PAUSED"):
            raise ApiError(ERR_ARCHIVE_BLOCKED, "Facility has non-cancelled standing orders", 409)
    f["status"] = "ARCHIVED"
    svc.touch(f)
    return success_object(facility_view(f))
