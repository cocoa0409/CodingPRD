"""Property inventory (PRD 3.1) including the OCC-guarded reclassify (PRD 2.7)."""
from flask import Blueprint, request

from db import db
from errors import raise_error, ERR_VALIDATION, ERR_STALE_PROPERTY_VERSION
from middleware import get_caller, check_role_allowed
from response import success_object
from routes.helpers import public, list_response, get_one
from services.core import new_record, touch, recompute_district_census
from validate import (
    get_body, req_str, req_enum, req_int, require_path_resource, require_body_ref,
)

bp = Blueprint("properties", __name__, url_prefix="/preservation")

CONTRIBUTING_STATUSES = {"CONTRIBUTING", "NON_CONTRIBUTING", "VACANT_LOT"}
STAFF = ["PreservationStaff"]


@bp.post("/properties")
def create_property():
    caller = get_caller()
    body = get_body()
    address = req_str(body, "address")
    parcel_number = req_str(body, "parcel_number")
    district_id = body.get("district_id")
    if district_id is not None and not isinstance(district_id, str):
        raise_error(ERR_VALIDATION, "invalid field type: district_id")
    owner_id = req_str(body, "owner_id")
    contributing_status = req_enum(body, "contributing_status", CONTRIBUTING_STATUSES)
    construction_year = req_int(body, "construction_year")
    assessed_value_cents = req_int(body, "assessed_value_cents", minimum=0)
    check_role_allowed(caller, STAFF)
    # Body-supplied references must exist (layer 3).
    if district_id is not None:
        require_body_ref("districts", district_id, "district_id")
    require_body_ref("owners", owner_id, "owner_id")
    # parcel_number is unique across the entire inventory.
    for p in db["properties"].values():
        if p.get("parcel_number") == parcel_number:
            raise_error(ERR_VALIDATION, f"parcel_number already exists: {parcel_number}")

    rec = new_record("properties", {
        "address": address,
        "parcel_number": parcel_number,
        "district_id": district_id,
        "owner_id": owner_id,
        "contributing_status": contributing_status,
        "construction_year": construction_year,
        "assessed_value_cents": assessed_value_cents,
        "listing_status": "INVENTORY",
        "open_violation_count": 0,
        "compliance_posture": "CLEAR",
    })
    recompute_district_census(district_id)
    return success_object(public(rec), status=201)


@bp.get("/properties")
def list_properties():
    filters = {
        "district_id": request.args.get("district_id"),
        "owner_id": request.args.get("owner_id"),
        "contributing_status": request.args.get("contributing_status"),
        "listing_status": request.args.get("listing_status"),
    }
    return list_response("properties", filters)


@bp.get("/properties/<rid>")
def get_property(rid):
    return get_one("properties", rid)


@bp.post("/properties/<rid>/reclassify")
def reclassify_property(rid):
    caller = get_caller()
    body = get_body()
    new_status = req_enum(body, "contributing_status", CONTRIBUTING_STATUSES)
    expected_version = req_int(body, "expected_property_version")
    check_role_allowed(caller, STAFF)
    prop = require_path_resource("properties", rid)
    # Pipeline layer 4 (OCC): the version check runs before any state or
    # business evaluation of the write.
    if expected_version != prop["version"]:
        raise_error(ERR_STALE_PROPERTY_VERSION,
                    f"expected_property_version {expected_version} != current version {prop['version']}")
    prop["contributing_status"] = new_status
    touch(prop)
    recompute_district_census(prop.get("district_id"))
    return success_object(public(prop))
