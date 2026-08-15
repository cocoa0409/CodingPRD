"""DisposalFacility endpoints (PRD §3.7)."""

from flask import Blueprint, request

import db
from errors import ApiError, ERR_FACILITY_NOT_FOUND, ERR_INVALID_ENUM, ERR_INVALID_REQUEST
from middleware import get_body, req_int, req_list, req_str, require_roles
from response import success_list, success_object
from services import cascades

bp = Blueprint("facilities", __name__)

ACCEPTED_STREAM_VALUES = {"USED_OIL", "ANTIFREEZE", "MIXED", "HALOGENATED"}
READ_ROLES = ("RoutePlanner", "Regulator", "EHSOfficer")


def get_facility_or_404(facility_id):
    facility = db.get("disposal_facilities", facility_id)
    if facility is None:
        raise ApiError(ERR_FACILITY_NOT_FOUND, "DisposalFacility id not found", 404)
    return facility


def serialize_facility(facility):
    out = db.serialize(facility)
    out["scheduled_gallons_today"] = cascades.facility_scheduled_gallons_today(facility["id"])
    return out


@bp.post("/disposal-facilities")
@require_roles("Regulator")
def create_facility():
    body = get_body()
    facility_name = req_str(body, "facility_name")
    epa_id = req_str(body, "epa_id")
    accepted_streams = req_list(body, "accepted_streams")
    daily_capacity_gallons = req_int(body, "daily_capacity_gallons", minimum=0)
    for stream in accepted_streams:
        if stream not in ACCEPTED_STREAM_VALUES:
            raise ApiError(
                ERR_INVALID_ENUM,
                "accepted_streams values must be one of ANTIFREEZE, HALOGENATED, MIXED, USED_OIL",
                400,
            )
    for f in db.all_entities("disposal_facilities"):
        if f["epa_id"] == epa_id:
            raise ApiError(ERR_INVALID_REQUEST, "epa_id must be unique", 400)
    facility = db.create_entity("disposal_facilities", {
        "facility_name": facility_name,
        "epa_id": epa_id,
        "accepted_streams": accepted_streams,
        "daily_capacity_gallons": daily_capacity_gallons,
        "status": "ACTIVE",
    })
    return success_object(serialize_facility(facility), 201)


@bp.get("/disposal-facilities")
@require_roles(*READ_ROLES)
def list_facilities():
    items = db.all_entities("disposal_facilities")
    status = request.args.get("status")
    if status is not None:
        items = [f for f in items if f["status"] == status]
    return success_list([serialize_facility(f) for f in db.sorted_created(items)])


@bp.get("/disposal-facilities/<facilityId>")
@require_roles(*READ_ROLES)
def get_facility(facilityId):
    return success_object(serialize_facility(get_facility_or_404(facilityId)))
