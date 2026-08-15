"""Vehicle endpoints."""
from flask import Blueprint, request

from db import store, new_record, touch
from errors import ApiError, err_not_found
from middleware import auth, require_fleet_ownership
from response import success
from serializers import serialize_vehicle
from services.cascades import wall_now
from util import Field, validate_body, parse_pagination, paginate

bp = Blueprint("vehicles", __name__)

CREATE_ROLES = ["OpsAdmin", "Dispatcher"]
READ_ROLES = ["OpsAdmin", "Dispatcher", "Technician", "FleetManager",
              "BillingClerk", "SafetyOfficer", "WarrantyAdministrator"]
LIST_ROLES = ["OpsAdmin", "Dispatcher", "FleetManager", "SafetyOfficer"]
PATCH_ROLES = ["OpsAdmin", "Dispatcher", "Technician"]


def _get_vehicle(vehicle_id):
    v = store.vehicles.get(vehicle_id)
    if v is None:
        raise err_not_found("Vehicle not found")
    return v


@bp.route("/roadside/vehicles", methods=["POST"])
def create_vehicle():
    auth(CREATE_ROLES)
    vals = validate_body(request.get_json(silent=True), [
        Field("vin", "string", required=True),
        Field("unit_number", "string", required=True),
        Field("make", "string", required=True),
        Field("model", "string", required=True),
        Field("year", "int", required=True),
        Field("odometer_miles", "int", min_val=0),
        Field("fleet_account_id", "string", nullable=True),
        Field("oem_warranty_expires_at", "datetime", nullable=True),
        Field("oem_warranty_miles_limit", "int", nullable=True, min_val=0),
        Field("extended_warranty", "bool"),
    ])
    fleet_id = vals.get("fleet_account_id")
    if fleet_id is not None and fleet_id not in store.fleets:
        raise err_not_found("FleetAccount not found")
    for v in store.vehicles.values():
        if v["vin"] == vals["vin"]:
            raise ApiError("ERR_DUPLICATE_VIN", "vin already exists", 409)
    rec = new_record()
    now = wall_now()
    rec.update({
        "_created": now, "_updated": now,
        "fleet_account_id": fleet_id,
        "vin": vals["vin"],
        "unit_number": vals["unit_number"],
        "make": vals["make"],
        "model": vals["model"],
        "year": vals["year"],
        "odometer_miles": vals.get("odometer_miles", 0),
        "oem_warranty_expires_at": vals.get("oem_warranty_expires_at"),
        "oem_warranty_miles_limit": vals.get("oem_warranty_miles_limit"),
        "extended_warranty": vals.get("extended_warranty", False),
    })
    store.vehicles[rec["id"]] = rec
    return success(serialize_vehicle(rec), status=201)


@bp.route("/roadside/vehicles/<vehicleId>", methods=["GET"])
def get_vehicle(vehicleId):
    uid, role = auth(READ_ROLES)
    v = _get_vehicle(vehicleId)
    if role == "FleetManager":
        require_fleet_ownership(uid, v.get("fleet_account_id"))
    return success(serialize_vehicle(v))


@bp.route("/roadside/vehicles", methods=["GET"])
def list_vehicles():
    uid, role = auth(LIST_ROLES)
    limit, offset = parse_pagination(request.args)
    fleet_f = request.args.get("fleet_account_id")
    road_f = request.args.get("roadworthiness")
    items = sorted(store.vehicles.values(), key=lambda r: r["_seq"])
    if role == "FleetManager":
        items = [v for v in items if v.get("fleet_account_id") == uid]
    if fleet_f is not None:
        items = [v for v in items if v.get("fleet_account_id") == fleet_f]
    if road_f is not None:
        items = [v for v in items
                 if serialize_vehicle(v)["roadworthiness"] == road_f]
    page, total, has_more = paginate(items, limit, offset)
    return success([serialize_vehicle(v) for v in page], response_type="array",
                   pagination={"limit": limit, "offset": offset,
                               "total_count": total, "has_more": has_more})


@bp.route("/roadside/vehicles/<vehicleId>", methods=["PATCH"])
def patch_vehicle(vehicleId):
    auth(PATCH_ROLES)
    v = _get_vehicle(vehicleId)
    vals = validate_body(request.get_json(silent=True), [
        Field("odometer_miles", "int", min_val=0),
        Field("unit_number", "string"),
        Field("oem_warranty_expires_at", "datetime", nullable=True),
        Field("oem_warranty_miles_limit", "int", nullable=True, min_val=0),
        Field("extended_warranty", "bool"),
    ])
    if "odometer_miles" in vals:
        if vals["odometer_miles"] < v["odometer_miles"]:
            raise ApiError("ERR_ODOMETER_REGRESSION",
                           "odometer input below vehicle.odometer_miles", 422)
    for k, val in vals.items():
        v[k] = val
    touch(v, wall_now())
    return success(serialize_vehicle(v))
