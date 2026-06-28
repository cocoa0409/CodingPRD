from flask import Blueprint, request

from db import db
from middleware import require_role
from response import object_response, array_response
from errors import err, ERR_DUPLICATE_RESOURCE, ERR_INVALID_STATE
from services.common import (
    stamp_create, touch, get_json_body, require_fields, require_string,
    parse_pagination, paginate,
)
from services.lookups import get_model, get_bike
from services.reconcile import recompute_model_counts
from services.serialize import bike_view

bikes_bp = Blueprint("bikes", __name__)

VIEW_ROLES = {"OpsAdmin", "FieldTech", "Subscriber", "FleetManager"}


@bikes_bp.route("/bikes", methods=["POST"])
def create_bike():
    require_role({"OpsAdmin"})
    body = get_json_body()
    require_fields(body, ["model_id", "serial_number"])
    require_string(body["model_id"], "model_id")
    require_string(body["serial_number"], "serial_number")
    with db.lock:
        # Existence (priority 3) before duplicate check (priority 16).
        get_model(body["model_id"])
        # Bike.serial_number globally unique.
        for b in db.bikes.values():
            if b["serial_number"] == body["serial_number"]:
                raise err(ERR_DUPLICATE_RESOURCE, "serial_number already exists.")
        rec = {
            "model_id": body["model_id"],
            "serial_number": body["serial_number"],
            "bike_status": "AVAILABLE",
            "current_rental_id": None,
        }
        stamp_create(rec)
        db.bikes[rec["id"]] = rec
        recompute_model_counts(rec["model_id"])
    return object_response(bike_view(rec), 201)


@bikes_bp.route("/bikes/<bike_id>", methods=["GET"])
def fetch_bike(bike_id):
    require_role(VIEW_ROLES)
    bike = get_bike(bike_id)
    return object_response(bike_view(bike), 200)


@bikes_bp.route("/bikes", methods=["GET"])
def list_bikes():
    require_role(VIEW_ROLES)
    limit, offset = parse_pagination()
    records = list(db.bikes.values())
    model_id = request.args.get("model_id")
    current_rental_id = request.args.get("current_rental_id")
    bike_status = request.args.get("bike_status")
    if model_id:
        records = [r for r in records if r["model_id"] == model_id]
    if current_rental_id:
        records = [r for r in records if r["current_rental_id"] == current_rental_id]
    if bike_status:
        records = [r for r in records if r["bike_status"] == bike_status]
    page, total = paginate(records, limit, offset)
    return array_response([bike_view(r) for r in page], limit, offset, total)


@bikes_bp.route("/bikes/<bike_id>/retire", methods=["POST"])
def retire_bike(bike_id):
    require_role({"OpsAdmin"})
    with db.lock:
        bike = get_bike(bike_id)
        # Only AVAILABLE -> RETIRED is defined (PRD §3.1).
        if bike["bike_status"] != "AVAILABLE":
            raise err(ERR_INVALID_STATE, "Bike must be AVAILABLE to retire.")
        bike["bike_status"] = "RETIRED"
        bike["current_rental_id"] = None
        touch(bike)
        recompute_model_counts(bike["model_id"])
    return object_response(bike_view(bike), 200)
