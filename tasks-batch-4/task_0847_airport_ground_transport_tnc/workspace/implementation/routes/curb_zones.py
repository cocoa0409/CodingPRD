from flask import Blueprint

import serializers
from common import authenticate, require_role, body_json, as_str, as_int, respond
from store import db, base_record

bp = Blueprint("curb_zones", __name__)


@bp.route("/v1/curb-zones", methods=["POST"])
def create_curb_zone():
    _uid, role = authenticate()
    require_role(role, {"AirportAuthority"})
    body = body_json()
    rec = base_record()
    rec.update({
        "name": as_str(body, "name"),
        "terminal": as_str(body, "terminal"),
        "capacity": as_int(body, "capacity"),
    })
    db.curb_zones[rec["id"]] = rec
    return respond(serializers.curb_zone(rec), "object", 201)
