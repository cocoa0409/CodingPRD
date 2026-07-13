from flask import Blueprint

import serializers
from common import authenticate, require_role, body_json, as_str, as_int, as_number, respond
from store import db, base_record

bp = Blueprint("staging_lots", __name__)


@bp.route("/v1/staging-lots", methods=["POST"])
def create_staging_lot():
    _uid, role = authenticate()
    require_role(role, {"AirportAuthority"})
    body = body_json()
    rec = base_record()
    rec.update({
        "name": as_str(body, "name"),
        "geofence_center_lat": as_number(body, "geofence_center_lat"),
        "geofence_center_lng": as_number(body, "geofence_center_lng"),
        "geofence_radius_m": as_number(body, "geofence_radius_m"),
        "capacity": as_int(body, "capacity"),
    })
    db.staging_lots[rec["id"]] = rec
    return respond(serializers.staging_lot(rec), "object", 201)
