"""Venue routes (PRD §3.1)."""
from flask import Blueprint, request

import errors
from db import db
from middleware import get_identity, require_role
from response import success, list_success
from services import serialize
from services.common import (
    new_record, get_body, get_or_404, paginate,
    req_str, req_int, opt_int, opt_number,
)

bp = Blueprint("venues", __name__)

READ_ROLES = {"GardenAdmin", "GardenStaff", "RentalCoordinator",
              "DevelopmentOfficer", "Visitor"}


@bp.route("/v1/venues", methods=["POST"])
def create_venue():
    _, role = get_identity()
    require_role(role, {"GardenAdmin", "RentalCoordinator"})
    body = get_body()
    garden_id = req_str(body, "garden_id")
    name = req_str(body, "name")
    hourly_rate_cents = req_int(body, "hourly_rate_cents", min_value=0)
    get_or_404(db.gardens, garden_id)
    rec = new_record({
        "garden_id": garden_id,
        "name": name,
        "hourly_rate_cents": hourly_rate_cents,
        "buffer_minutes": opt_int(body, "buffer_minutes", 60),
        "member_rental_discount_pct": opt_number(body, "member_rental_discount_pct", 0.15),
    })
    db.venues[rec["id"]] = rec
    return success(serialize.venue(rec), status=201)


@bp.route("/v1/venues/<venue_id>", methods=["GET"])
def read_venue(venue_id):
    _, role = get_identity()
    require_role(role, READ_ROLES)
    rec = get_or_404(db.venues, venue_id)
    return success(serialize.venue(rec), status=200)


@bp.route("/v1/venues", methods=["GET"])
def list_venues():
    _, role = get_identity()
    require_role(role, READ_ROLES)
    garden_id = request.args.get("garden_id")
    records = list(db.venues.values())
    if garden_id is not None:
        records = [r for r in records if r["garden_id"] == garden_id]
    page, limit, offset, total = paginate(records)
    return list_success([serialize.venue(r) for r in page],
                        limit, offset, total)
