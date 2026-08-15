"""Venue endpoints: POST /venues, GET /venues/{id}."""

from flask import Blueprint

import db
from errors import err, ERR_NOT_FOUND
from middleware import authenticate, require_roles
from response import success
from util import (get_body, reject_unknown, require_present, as_int, as_str)

bp = Blueprint("venues", __name__)


@bp.route("/venues", methods=["POST"])
def create_venue():
    _, role = authenticate()
    require_roles(role, ("Producer",))
    body = get_body()
    reject_unknown(body, {"name", "city", "stage_width_ft", "fly_capacity_lines",
                          "power_amps", "crew_available"})
    rec = db.new_record()
    rec.update({
        "name": as_str(require_present(body, "name"), "name"),
        "city": as_str(require_present(body, "city"), "city"),
        "stage_width_ft": as_int(require_present(body, "stage_width_ft"),
                                 "stage_width_ft", minv=1),
        "fly_capacity_lines": as_int(require_present(body, "fly_capacity_lines"),
                                     "fly_capacity_lines", minv=0),
        "power_amps": as_int(require_present(body, "power_amps"),
                             "power_amps", minv=1),
        "crew_available": as_int(require_present(body, "crew_available"),
                                 "crew_available", minv=0),
    })
    db.venues[rec["id"]] = rec
    return success(db.serialize("venue", rec), 201)


@bp.route("/venues/<venue_id>", methods=["GET"])
def get_venue(venue_id):
    authenticate()
    venue = db.venues.get(venue_id)
    if venue is None:
        raise err(ERR_NOT_FOUND, 404, "Venue not found")
    return success(db.serialize("venue", venue), 200)
