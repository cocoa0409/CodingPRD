"""Halls and seating sections."""

from flask import Blueprint, request

from db import db
from domain import base_fields, serialize, touch
from errors import raise_err
from middleware import endpoint
from response import ok, ok_list
from validate import (body, check_body_fks, opt_int, paginate, req_int,
                      req_str)

bp = Blueprint("venues", __name__)


def get_venue_or_404(venue_id):
    venue = db.venues.get(venue_id)
    if venue is None:
        raise_err("ERR_VENUE_NOT_FOUND")
    return venue


def get_section_or_404(section_id):
    section = db.sections.get(section_id)
    if section is None:
        raise_err("ERR_SECTION_NOT_FOUND")
    return section


@bp.route("/orchestra/venues", methods=["POST"])
@endpoint(["ArtisticAdmin"])
def create_venue():
    data = body()
    check_body_fks(data, [])
    name = req_str(data, "name")
    buffer_minutes = opt_int(data, "changeover_buffer_minutes", 60, minv=0)

    venue = base_fields()
    venue.update({
        "name": name,
        "changeover_buffer_minutes": buffer_minutes,
        "total_capacity": 0,
    })
    db.venues[venue["id"]] = venue
    return ok(serialize(venue), 201)


@bp.route("/orchestra/venues/<venue_id>", methods=["GET"])
@endpoint(["ArtisticAdmin", "OrchestraManager", "BoxOfficeAgent"])
def read_venue(venue_id):
    return ok(serialize(get_venue_or_404(venue_id)))


@bp.route("/orchestra/sections", methods=["POST"])
@endpoint(["ArtisticAdmin"])
def create_section():
    data = body()
    check_body_fks(data, ["venue_id"])                      # rung 4
    venue = db.venues.get(data.get("venue_id"))
    if venue is None:
        # venue_id absent entirely -- reported as a shape failure at rung 6
        req_str(data, "venue_id")
        raise_err("ERR_VENUE_NOT_FOUND")
    name = req_str(data, "name")
    capacity = req_int(data, "capacity", minv=1)
    multiplier = req_int(data, "price_multiplier_bp", minv=1)
    rank = req_int(data, "donor_priority_rank", minv=1, maxv=5)
    min_score = opt_int(data, "min_renewal_priority_score", 0, minv=0)

    section = base_fields()
    section.update({
        "venue_id": venue["id"],
        "name": name,
        "capacity": capacity,
        "price_multiplier_bp": multiplier,
        "donor_priority_rank": rank,
        "min_renewal_priority_score": min_score,
    })
    db.sections[section["id"]] = section
    with touch(venue):
        venue["total_capacity"] += capacity
    return ok(serialize(section), 201)


@bp.route("/orchestra/sections/<section_id>", methods=["GET"])
@endpoint(["ArtisticAdmin", "OrchestraManager", "BoxOfficeAgent", "Patron"])
def read_section(section_id):
    return ok(serialize(get_section_or_404(section_id)))


@bp.route("/orchestra/sections", methods=["GET"])
@endpoint(["ArtisticAdmin", "OrchestraManager", "BoxOfficeAgent", "Patron"])
def list_sections():
    venue_id = request.args.get("venue_id")
    records = [s for s in db.sections.values()
               if venue_id is None or s["venue_id"] == venue_id]
    items, limit, offset, total = paginate(records, serialize)
    return ok_list(items, limit, offset, total)
