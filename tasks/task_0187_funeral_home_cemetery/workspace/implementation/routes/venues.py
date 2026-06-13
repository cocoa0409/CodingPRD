from flask import Blueprint, request

import db
import validate
import serialize
from response import ok_object, ok_array
from middleware import require
from services import lookup

bp = Blueprint("venues", __name__)


@bp.post("/venues")
@require("Admin")
def create_venue():
    body = validate.get_json()
    funeral_home_id = validate.require_string(body, "funeral_home_id")
    name = validate.require_string(body, "name")
    capacity = validate.require_int(body, "capacity", minimum=1)

    lookup.funeral_home(funeral_home_id)

    venue = {
        "id": db.new_id(),
        "funeral_home_id": funeral_home_id,
        "name": name,
        "capacity": capacity,
    }
    db.stamp_create(venue)
    db.venues[venue["id"]] = venue
    return ok_object(serialize.venue(venue), 201)


@bp.get("/venues/<venue_id>")
@require("Admin", "Arranger", "CemeteryClerk")
def get_venue(venue_id):
    venue = lookup.venue(venue_id)
    return ok_object(serialize.venue(venue), 200)


@bp.get("/venues")
@require("Admin", "Arranger", "CemeteryClerk")
def list_venues():
    limit, offset = validate.pagination()
    fh = request.args.get("funeral_home_id")
    items = list(db.venues.values())
    if fh is not None:
        items = [v for v in items if v["funeral_home_id"] == fh]
    window, total = validate.paginate(items, limit, offset)
    return ok_array([serialize.venue(v) for v in window], limit, offset, total)
