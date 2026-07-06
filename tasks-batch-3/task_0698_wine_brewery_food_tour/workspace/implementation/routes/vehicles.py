"""Vehicle (van) endpoints (PRD §3.2)."""
from flask import Blueprint
import errors
import validate
import serialize
from db import db
from middleware import require_auth
from records import new_record, touch
from response import object_response

bp = Blueprint("vehicles", __name__)

READ_ROLES = {"Operator", "Guide"}


@bp.post("/vehicles")
def create():
    require_auth({"Operator"})
    body = validate.get_json_body()
    validate.require_fields(body, ["label", "seat_capacity"])
    label = validate.require_str(body, "label")
    seat_capacity = validate.require_int(body, "seat_capacity")
    if seat_capacity <= 0:
        validate.out_of_range()
    rec = new_record({
        "label": label,
        "seat_capacity": seat_capacity,
        "status": "AVAILABLE",
    })
    db.vehicles[rec["id"]] = rec
    return object_response(serialize.vehicle(rec), status=201)


@bp.get("/vehicles/<vid>")
def get_vehicle(vid):
    require_auth(READ_ROLES)
    rec = db.vehicles.get(vid)
    if rec is None:
        raise errors.err(errors.ERR_NOT_FOUND, "Vehicle not found")
    return object_response(serialize.vehicle(rec), status=200)


@bp.post("/vehicles/<vid>/set-status")
def set_status(vid):
    require_auth({"Operator"})
    rec = db.vehicles.get(vid)
    if rec is None:
        raise errors.err(errors.ERR_NOT_FOUND, "Vehicle not found")
    body = validate.get_json_body()
    validate.require_fields(body, ["status"])
    status = body["status"]
    if not isinstance(status, str):
        raise errors.err(errors.ERR_INVALID_REQUEST, "status must be a string")
    validate.check_enum(status, validate.VEHICLE_STATUS_VALUES, "status")
    rec["status"] = status
    touch(rec)
    return object_response(serialize.vehicle(rec), status=200)
