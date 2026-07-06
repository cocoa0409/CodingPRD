"""PickupPoint endpoints (PRD §3.2)."""
from flask import Blueprint
import errors
import validate
import serialize
from db import db
from middleware import require_auth, resolve_reader
from records import new_record
from response import object_response

bp = Blueprint("pickup_points", __name__)

READ_ROLES = {"Operator", "Guest", "Anonymous"}


@bp.post("/pickup-points")
def create():
    require_auth({"Operator"})
    body = validate.get_json_body()
    validate.require_fields(body, ["name", "address"])
    name = validate.require_str(body, "name")
    address = validate.require_str(body, "address")
    rec = new_record({
        "name": name,
        "address": address,
        "status": "ACTIVE",
    })
    db.pickup_points[rec["id"]] = rec
    return object_response(serialize.pickup_point(rec), status=201)


@bp.get("/pickup-points/<ppid>")
def get_pickup(ppid):
    resolve_reader(READ_ROLES)
    rec = db.pickup_points.get(ppid)
    if rec is None:
        raise errors.err(errors.ERR_NOT_FOUND, "Pickup point not found")
    return object_response(serialize.pickup_point(rec), status=200)
