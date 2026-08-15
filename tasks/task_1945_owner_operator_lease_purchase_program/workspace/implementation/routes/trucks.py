"""Truck routes."""

from flask import Blueprint

import errors
import middleware
from db import db
from response import success
from services.core import base_entity, touch
from services.serialize import serialize_truck
from util import get_body, req_str, req_int, req_dt

bp = Blueprint("trucks", __name__)


@bp.post("/trucks")
def create_truck():
    middleware.require_roles({"LeaseAdmin"})
    body = get_body()
    vin = req_str(body, "vin")
    year = req_int(body, "year")
    make = req_str(body, "make")
    model = req_str(body, "model")
    odometer_current = req_int(body, "odometer_current")
    warranty_expires = req_dt(body, "powertrain_warranty_expires_on")
    warranty_limit = req_int(body, "powertrain_warranty_mileage_limit")

    for t in db.trucks.values():
        if t["vin"] == vin:
            raise errors.err(errors.ERR_DUPLICATE_VALUE, "vin must be unique", 409)

    truck = base_entity()
    truck.update({
        "vin": vin,
        "year": year,
        "make": make,
        "model": model,
        "odometer_current": odometer_current,
        "_warranty_expires_on": warranty_expires,
        "powertrain_warranty_mileage_limit": warranty_limit,
        "status": "AVAILABLE",
    })
    db.trucks[truck["id"]] = truck
    return success(serialize_truck(truck), "object", 201)


@bp.get("/trucks/<truck_id>")
def get_truck(truck_id):
    middleware.require_roles(middleware.ALL_ROLES)
    truck = db.trucks.get(truck_id)
    if truck is None:
        raise errors.err(errors.ERR_TRUCK_NOT_FOUND, "Truck not found", 404)
    return success(serialize_truck(truck), "object", 200)


@bp.post("/trucks/<truck_id>/confirm-return")
def confirm_return(truck_id):
    middleware.require_roles({"LeaseAdmin"})
    truck = db.trucks.get(truck_id)
    if truck is None:
        raise errors.err(errors.ERR_TRUCK_NOT_FOUND, "Truck not found", 404)
    if truck["status"] != "IN_RETURN":
        raise errors.err(errors.ERR_TRUCK_NOT_IN_RETURN, "Truck is not IN_RETURN", 409)
    truck["status"] = "RETURNED"
    touch(truck)
    return success(serialize_truck(truck), "object", 200)


@bp.post("/trucks/<truck_id>/relist")
def relist(truck_id):
    middleware.require_roles({"LeaseAdmin"})
    truck = db.trucks.get(truck_id)
    if truck is None:
        raise errors.err(errors.ERR_TRUCK_NOT_FOUND, "Truck not found", 404)
    if truck["status"] != "RETURNED":
        raise errors.err(errors.ERR_TRUCK_NOT_RETURNED, "Truck is not RETURNED", 409)
    truck["status"] = "AVAILABLE"
    touch(truck)
    return success(serialize_truck(truck), "object", 200)
