"""Location endpoints (PRD §3.1)."""
from flask import Blueprint, request

import db
import lookup
import serialize
import util
from errors import err
from middleware import get_principal, require_roles
from pagination import paginate
from response import array_response, object_response

bp = Blueprint("locations", __name__)


@bp.route("/locations", methods=["POST"])
def create_location():
    _, role = get_principal()
    require_roles(role, {"FleetManager"})
    body = request.get_json(silent=True) or {}

    code = util.require_str(body, "code")
    name = util.require_str(body, "name")
    one_way = util.require_int(body, "one_way_drop_fee_cents", minimum=0)
    young = util.require_int(body, "young_driver_surcharge_per_day_cents", minimum=0)

    # code must be uppercase and unique across Location.
    if code != code.upper():
        raise err("ERR_INVALID_REQUEST", "Location code must be uppercase")
    for existing in db.locations.values():
        if existing["code"] == code:
            raise err("ERR_INVALID_REQUEST", "Location code already exists: %s" % code)

    rec = util.stamp_new(
        {
            "code": code,
            "name": name,
            "one_way_drop_fee_cents": one_way,
            "young_driver_surcharge_per_day_cents": young,
        }
    )
    db.locations[rec["id"]] = rec
    return object_response(serialize.location(rec), 201)


@bp.route("/locations/<loc_id>", methods=["GET"])
def get_location(loc_id):
    _, role = get_principal()
    require_roles(role, {"FleetManager", "RentalAgent", "Member"})
    rec = lookup.get_location(loc_id)
    return object_response(serialize.location(rec), 200)


@bp.route("/locations/<loc_id>/vehicles", methods=["GET"])
def list_location_vehicles(loc_id):
    _, role = get_principal()
    require_roles(role, {"FleetManager", "RentalAgent"})
    lookup.get_location(loc_id)

    status = request.args.get("status")
    class_id = request.args.get("class_id")
    matches = [
        v
        for v in db.vehicles.values()
        if v["location_id"] == loc_id
        and (status is None or v["status"] == status)
        and (class_id is None or v["class_id"] == class_id)
    ]
    page, limit, offset, total = paginate(matches)
    return array_response(
        [serialize.vehicle(v) for v in page], limit, offset, total, 200
    )
