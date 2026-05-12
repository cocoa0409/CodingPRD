"""Vehicles."""

from flask import Blueprint, request

import db
import errors
import helpers
import response
import serializers
from middleware import auth_required
from services import audit


bp = Blueprint("vehicles", __name__, url_prefix="/supply-chain/vehicles")


VALID_ZONES = {"AMBIENT", "CHILLED", "FROZEN"}


@bp.route("", methods=["POST"])
@auth_required("PlatformAdmin")
def create_vehicle():
    body = helpers.get_json_body()
    for f in ["vehicle_code", "capacity_units", "temperature_zones"]:
        if f not in body:
            errors.raise_error(errors.ERR_QUANTITY_OUT_OF_RANGE, f"Missing field: {f}")
    if not isinstance(body["capacity_units"], int) or body["capacity_units"] <= 0:
        errors.raise_error(errors.ERR_QUANTITY_OUT_OF_RANGE, "capacity_units must be a positive integer.")
    zones = body["temperature_zones"]
    if not isinstance(zones, list) or not zones:
        errors.raise_error(errors.ERR_QUANTITY_OUT_OF_RANGE, "temperature_zones must be a non-empty array.")
    for z in zones:
        if z not in VALID_ZONES:
            errors.raise_error(errors.ERR_QUANTITY_OUT_OF_RANGE, f"Invalid zone: {z}")

    vid = db.new_id()
    common = helpers.common_create()
    vehicle = {
        "id": vid,
        "vehicle_code": body["vehicle_code"],
        "capacity_units": body["capacity_units"],
        "temperature_zones": list(zones),
        "status": "AVAILABLE",
        **common,
    }
    db.vehicles[vid] = vehicle
    audit.append(target_type="Vehicle", target_id=vid, action="CREATE_VEHICLE",
                 payload={"vehicle_code": vehicle["vehicle_code"]})
    return response.created(serializers.vehicle_dict(vehicle))


@bp.route("", methods=["GET"])
@auth_required("PlatformAdmin", "CentralKitchenPlanner")
def list_vehicles():
    limit, offset = helpers.parse_pagination()
    items = list(db.vehicles.values())
    status_filter = request.args.get("status")
    if status_filter:
        items = [v for v in items if v["status"] == status_filter]
    items.sort(key=lambda v: v["created_at"])
    page, total = helpers.paginate(items, limit, offset)
    return response.list_ok([serializers.vehicle_dict(v) for v in page],
                            limit=limit, offset=offset, total_count=total)
