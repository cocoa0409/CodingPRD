"""Vehicle endpoints."""

from flask import Blueprint, request

import errors
import serializers
from db import stamp_new, store
from envelope import ok
from listing import page_out
from validators import (
    VEHICLE_CLASSES,
    as_enum,
    as_str,
    body,
    endpoint,
    get_or_404,
    req,
)

bp = Blueprint("vehicles", __name__)

ALL_ROLES = ["CarrierAdmin", "ShipperComplianceOfficer", "Regulator"]


def _vehicle_or_404(vehicle_id):
    return get_or_404(store.vehicles, vehicle_id, errors.ERR_VEHICLE_NOT_FOUND,
                      "Vehicle")


@bp.route("/hazmat/carriers/<carrierId>/vehicles", methods=["POST"])
@endpoint(["CarrierAdmin"])
def create_vehicle(uid, role, carrierId):
    carrier = get_or_404(store.carriers, carrierId, errors.ERR_CARRIER_NOT_FOUND,
                         "Carrier")
    b = body()
    plate = as_str(req(b, "plate_number"), "plate_number")
    vehicle_class = as_enum(req(b, "vehicle_class"), "vehicle_class", VEHICLE_CLASSES)
    if carrier["registration_status"] != "APPROVED_ACTIVE":
        raise errors.conflict(errors.ERR_CARRIER_NOT_ACTIVE,
                              "Carrier must be APPROVED_ACTIVE to register vehicles")
    for v in store.vehicles.values():
        if v["plate_number"] == plate:
            raise errors.conflict(errors.ERR_DUPLICATE_PLATE,
                                  "plate_number already registered")
    vehicle = {
        "carrier_id": carrier["id"],
        "plate_number": plate,
        "vehicle_class": vehicle_class,
        "status": "AVAILABLE",
    }
    stamp_new(vehicle)
    store.vehicles[vehicle["id"]] = vehicle
    return ok(serializers.vehicle(vehicle), 201)


@bp.route("/hazmat/carriers/<carrierId>/vehicles", methods=["GET"])
@endpoint(ALL_ROLES)
def list_vehicles(uid, role, carrierId):
    carrier = get_or_404(store.carriers, carrierId, errors.ERR_CARRIER_NOT_FOUND,
                         "Carrier")
    rows = [v for v in store.vehicles.values() if v["carrier_id"] == carrier["id"]]
    status = request.args.get("status")
    if status is not None:
        rows = [v for v in rows if v["status"] == status]
    return page_out(rows, serializers.vehicle)


@bp.route("/hazmat/vehicles/<vehicleId>", methods=["GET"])
@endpoint(ALL_ROLES)
def get_vehicle(uid, role, vehicleId):
    return ok(serializers.vehicle(_vehicle_or_404(vehicleId)), 200)
