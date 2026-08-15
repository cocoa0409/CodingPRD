"""Driver endpoints (PRD §3.3)."""

from flask import Blueprint, request

import db
from errors import ApiError, ERR_DRIVER_NOT_FOUND, ERR_DRIVER_SUSPENDED
from middleware import get_body, req_bool, req_enum, req_str, require_roles
from response import success_list, success_object

bp = Blueprint("drivers", __name__)

CDL_CLASSES = {"A", "B", "C"}


def get_driver_or_404(driver_id):
    driver = db.get("drivers", driver_id)
    if driver is None:
        raise ApiError(ERR_DRIVER_NOT_FOUND, "Driver id not found", 404)
    return driver


@bp.post("/drivers")
@require_roles("RoutePlanner")
def create_driver():
    body = get_body()
    driver = db.create_entity("drivers", {
        "driver_name": req_str(body, "driver_name"),
        "cdl_class": req_enum(body, "cdl_class", CDL_CLASSES),
        "hazmat_endorsement": req_bool(body, "hazmat_endorsement"),
        "status": "ACTIVE",
    })
    return success_object(db.serialize(driver), 201)


@bp.get("/drivers")
@require_roles("RoutePlanner", "EHSOfficer")
def list_drivers():
    items = db.all_entities("drivers")
    status = request.args.get("status")
    if status is not None:
        items = [d for d in items if d["status"] == status]
    return success_list([db.serialize(d) for d in db.sorted_created(items)])


@bp.get("/drivers/<driverId>")
@require_roles("RoutePlanner", "EHSOfficer", "Driver")
def get_driver(driverId):
    return success_object(db.serialize(get_driver_or_404(driverId)))


@bp.post("/drivers/<driverId>/suspend")
@require_roles("RoutePlanner")
def suspend_driver(driverId):
    driver = get_driver_or_404(driverId)
    if driver["status"] != "ACTIVE":
        raise ApiError(ERR_DRIVER_SUSPENDED, "Driver suspended", 409)
    driver["status"] = "SUSPENDED"
    db.touch(driver)
    return success_object(db.serialize(driver))
