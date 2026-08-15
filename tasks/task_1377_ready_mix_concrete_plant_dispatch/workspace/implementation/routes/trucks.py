"""Truck routes."""

from flask import Blueprint

import clock
import errors
import middleware as mw
import response
from db import stores
from routes.catalog import get_or_404, request_args

bp = Blueprint("trucks", __name__)

DISPATCHER = ["Dispatcher"]


@bp.post("/v1/trucks")
def create_truck():
    mw.require_auth(DISPATCHER)
    body = mw.get_json_body()
    plant_id = mw.require_string(body, "plant_id")
    get_or_404("plants", plant_id)
    fleet_number = mw.require_string(body, "fleet_number")
    capacity_yd3 = mw.require_number(body, "capacity_yd3")
    for t in stores["trucks"].values():
        if t["plant_id"] == plant_id and t["fleet_number"] == fleet_number:
            raise errors.err_validation("Duplicate fleet_number for plant")
    rec = mw.new_record()
    rec["plant_id"] = plant_id
    rec["fleet_number"] = fleet_number
    rec["capacity_yd3"] = capacity_yd3
    rec["status"] = "AVAILABLE"
    rec["last_available_at"] = clock.iso(clock.now())
    stores["trucks"][rec["id"]] = rec
    return response.success_object(rec, 201)


@bp.get("/v1/trucks/<rid>")
def get_truck(rid):
    mw.require_auth(mw.ALL_ROLES)
    return response.success_object(get_or_404("trucks", rid))


@bp.get("/v1/trucks")
def list_trucks():
    mw.require_auth(mw.ALL_ROLES)
    limit, offset = mw.parse_pagination()
    items = list(stores["trucks"].values())
    plant_id = mw.optional_string(request_args(), "plant_id")
    status = mw.optional_string(request_args(), "status")
    if plant_id is not None:
        items = [t for t in items if t["plant_id"] == plant_id]
    if status is not None:
        items = [t for t in items if t["status"] == status]
    page, total = mw.sort_and_page(items, limit, offset)
    return response.success_array(page, limit, offset, total)


@bp.post("/v1/trucks/<rid>/out-of-service")
def out_of_service(rid):
    mw.require_auth(DISPATCHER)
    rec = get_or_404("trucks", rid)
    if rec["status"] != "AVAILABLE":
        raise errors.err_invalid_state()
    rec["status"] = "OUT_OF_SERVICE"
    mw.touch(rec)
    return response.success_object(rec)


@bp.post("/v1/trucks/<rid>/return-to-service")
def return_to_service(rid):
    mw.require_auth(DISPATCHER)
    rec = get_or_404("trucks", rid)
    if rec["status"] != "OUT_OF_SERVICE":
        raise errors.err_invalid_state()
    rec["status"] = "AVAILABLE"
    rec["last_available_at"] = clock.iso(clock.now())
    mw.touch(rec)
    return response.success_object(rec)
