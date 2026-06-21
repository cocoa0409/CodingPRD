"""DiningArea routes (PRD §3.1)."""
from flask import Blueprint, request

import db
from middleware import require_roles
from response import object_response, array_response
from services.lookup import get_or_404
from validators import get_body, require_str, opt_enum, paginate

bp = Blueprint("dining_areas", __name__)


@bp.post("/dining-areas")
def create_dining_area():
    require_roles({"Manager"})
    body = get_body()
    restaurant_id = require_str(body, "restaurant_id")
    get_or_404(db.restaurants, restaurant_id)
    name = require_str(body, "name")
    kind = opt_enum(body, "kind", {"STANDARD", "PRIVATE"}, "STANDARD")

    rec = db.base_fields()
    rec.update({
        "restaurant_id": restaurant_id,
        "name": name,
        "kind": kind,
        "status": "AVAILABLE",
    })
    db.dining_areas[rec["id"]] = rec
    return object_response(db.serialize(rec), 201)


@bp.get("/dining-areas/<aid>")
def read_dining_area(aid):
    require_roles({"Manager", "Host", "Customer"})
    rec = get_or_404(db.dining_areas, aid)
    return object_response(db.serialize(rec), 200)


@bp.get("/dining-areas")
def list_dining_areas():
    require_roles({"Manager", "Host", "Customer"})
    restaurant_id = request.args.get("restaurant_id")
    records = [a for a in db.dining_areas.values()
               if restaurant_id is None or a["restaurant_id"] == restaurant_id]
    page, pagination = paginate(records)
    return array_response([db.serialize(r) for r in page], pagination, 200)
