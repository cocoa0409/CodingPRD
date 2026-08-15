"""Vehicle endpoints."""

from flask import Blueprint, request

from db import store
from serialize import ser_vehicle
from util import (
    caller, require_role, forbid, get_body, respond, paginate, req_str,
    req_enum, stamp_new, ApiError,
)
from errors import ERR_NOT_FOUND, ERR_VALIDATION

bp = Blueprint("vehicles", __name__)

VEHICLE_CLASSES = {"SEDAN", "SUV_PICKUP", "VAN_BOXTRUCK", "HEAVY_FLEET"}


@bp.post("/fleet-wash/vehicles")
def create_vehicle():
    uid, role = caller()
    require_role(role, {"PlatformAdmin", "Customer"})
    body = get_body()
    customer_id = req_str(body, "customer_id")
    if role == "Customer" and customer_id != uid:
        forbid("Customers may only register their own vehicles")
    if customer_id not in store.customers:
        raise ApiError(ERR_NOT_FOUND, "Customer %s not found" % customer_id)
    site_id = req_str(body, "site_id")
    if site_id not in store.sites:
        raise ApiError(ERR_NOT_FOUND, "Site %s not found" % site_id)
    plate = req_str(body, "plate")
    vclass = req_enum(body, "vehicle_class", VEHICLE_CLASSES)
    for v in store.vehicles.values():
        if v["plate"] == plate:
            raise ApiError(ERR_VALIDATION, "plate must be unique across vehicles")
    rec = {
        "customer_id": customer_id,
        "site_id": site_id,
        "plate": plate,
        "vehicle_class": vclass,
    }
    stamp_new(rec)
    store.vehicles[rec["id"]] = rec
    return respond(ser_vehicle(rec), 201)


@bp.get("/fleet-wash/vehicles/<vid>")
def get_vehicle(vid):
    uid, role = caller()
    rec = store.vehicles.get(vid)
    if rec is None:
        raise ApiError(ERR_NOT_FOUND, "Vehicle %s not found" % vid)
    if role == "Customer" and rec["customer_id"] != uid:
        forbid("Customers may only access their own vehicles")
    return respond(ser_vehicle(rec), 200)


@bp.get("/fleet-wash/vehicles")
def list_vehicles():
    uid, role = caller()
    customer_id = request.args.get("customer_id")
    site_id = request.args.get("site_id")
    if role == "Customer":
        if customer_id is not None and customer_id != uid:
            forbid("Customers may only list their own vehicles")
        customer_id = uid
    recs = list(store.vehicles.values())
    if customer_id is not None:
        recs = [v for v in recs if v["customer_id"] == customer_id]
    if site_id is not None:
        recs = [v for v in recs if v["site_id"] == site_id]
    return paginate(recs, ser_vehicle)
