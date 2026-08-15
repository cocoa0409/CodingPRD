"""Vessel endpoints (PRD §3.1)."""

from flask import Blueprint, request

from db import db, now_iso
from errors import raise_error, ERR_NOT_FOUND, ERR_DUPLICATE
from middleware import require_roles
from response import success_object, success_list, parse_pagination, paginate
from services.serializers import serialize_vessel
from services.sailing_ops import vessel_out_of_service_cascade

bp = Blueprint("vessels", __name__)

ALL_ROLES = ("SchedulerAdmin", "TerminalAgent", "CrewPlanner", "Customer")


@bp.post("/ferry/vessels")
def create_vessel():
    require_roles("SchedulerAdmin")
    payload = request.get_json(silent=True) or {}
    vessel_name = payload.get("vessel_name")

    # ERR_DUPLICATE: vessel_name unique
    for v in db.vessels.values():
        if v["vessel_name"] == vessel_name:
            raise_error(ERR_DUPLICATE, "vessel_name already in use")

    ts = now_iso()
    vessel = {
        "id": db.new_id(),
        "vessel_name": vessel_name,
        "vehicle_deck_linear_feet": payload.get("vehicle_deck_linear_feet"),
        "passenger_capacity": payload.get("passenger_capacity"),
        "crew_class": payload.get("crew_class"),
        "status": "IN_SERVICE",
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    db.vessels[vessel["id"]] = vessel
    return success_object(serialize_vessel(vessel), status=201)


@bp.get("/ferry/vessels/<vessel_id>")
def get_vessel(vessel_id):
    require_roles(*ALL_ROLES)
    vessel = db.vessels.get(vessel_id)
    if vessel is None:
        raise_error(ERR_NOT_FOUND, "Vessel not found")
    return success_object(serialize_vessel(vessel))


@bp.get("/ferry/vessels")
def list_vessels():
    require_roles(*ALL_ROLES)
    status = request.args.get("status")
    items = [v for v in db.vessels.values() if status is None or v["status"] == status]
    items.sort(key=lambda v: (v["created_at"], v["id"]))
    limit, offset = parse_pagination(request.args)
    page, meta = paginate(items, limit, offset)
    return success_list([serialize_vessel(v) for v in page], meta)


@bp.post("/ferry/vessels/<vessel_id>/set-out-of-service")
def set_out_of_service(vessel_id):
    require_roles("SchedulerAdmin")
    vessel = db.vessels.get(vessel_id)
    if vessel is None:
        raise_error(ERR_NOT_FOUND, "Vessel not found")
    vessel_out_of_service_cascade(vessel)
    return success_object(serialize_vessel(vessel))
