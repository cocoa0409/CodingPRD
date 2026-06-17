"""ParkingSpot endpoints (PRD §3.4)."""
from flask import Blueprint, request

import db
import errors
from errors import err
from middleware import authenticate, require_role
from response import success, list_response
from helpers import (get_json, require_string, require_enum,
                     pagination_params, paginate)

bp = Blueprint("parking_spots", __name__)


def spot_view(s):
    return {
        "id": s["id"],
        "label": s["label"],
        "spot_type": s["spot_type"],
        "max_weight_class": s["max_weight_class"],
        "spot_status": s["spot_status"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


@bp.route("/parking-spots", methods=["POST"])
def create_spot():
    _, role = authenticate()
    require_role(role, {"OpsDispatcher", "LineManager"})
    body = get_json()
    label = require_string(body, "label")
    spot_type = require_enum(body, "spot_type", {"HANGAR", "TIE_DOWN", "RAMP"})
    max_weight_class = require_enum(body, "max_weight_class", {"LIGHT", "MID", "HEAVY"})

    for s in db.parking_spots.values():
        if s["label"] == label:
            raise err(errors.ERR_DUPLICATE_RESOURCE, "Duplicate parking spot label.")

    s = db.common_create()
    s.update({
        "label": label,
        "spot_type": spot_type,
        "max_weight_class": max_weight_class,
        "spot_status": "AVAILABLE",
    })
    db.parking_spots[s["id"]] = s
    return success(spot_view(s), 201)


@bp.route("/parking-spots/<id>", methods=["GET"])
def get_spot(id):
    _, role = authenticate()
    require_role(role, {"OpsDispatcher", "LineManager", "Operator"})
    s = db.parking_spots.get(id)
    if s is None:
        raise err(errors.ERR_NOT_FOUND, "Parking spot not found.")
    return success(spot_view(s), 200)


@bp.route("/parking-spots", methods=["GET"])
def list_spots():
    _, role = authenticate()
    require_role(role, {"OpsDispatcher", "LineManager", "Operator"})
    limit, offset = pagination_params()
    records = list(db.parking_spots.values())
    t_f = request.args.get("spot_type")
    s_f = request.args.get("spot_status")
    if t_f is not None:
        records = [r for r in records if r["spot_type"] == t_f]
    if s_f is not None:
        records = [r for r in records if r["spot_status"] == s_f]
    window, total = paginate(records, limit, offset)
    return list_response([spot_view(r) for r in window], limit, offset, total)


@bp.route("/parking-spots/<id>/out-of-service", methods=["POST"])
def out_of_service(id):
    _, role = authenticate()
    require_role(role, {"OpsDispatcher", "LineManager"})
    s = db.parking_spots.get(id)
    if s is None:
        raise err(errors.ERR_NOT_FOUND, "Parking spot not found.")
    s["spot_status"] = "OUT_OF_SERVICE"
    db.touch(s)
    return success(spot_view(s), 200)
