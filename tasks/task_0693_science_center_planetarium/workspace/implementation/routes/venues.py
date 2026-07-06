"""Venue endpoints (PRD §3.1)."""
from flask import Blueprint, request

from db import db, new_record
from errors import err, ERR_VALIDATION
from middleware import authenticate, require_role
from response import success
from services.common import (
    get_body,
    require_string,
    require_enum,
    require_int,
    optional_int,
    validate_range,
    parse_pagination,
    paginate,
)
from services.lookups import get_venue
from services.serialize import venue_view, show_view, program_view, rental_view

bp = Blueprint("venues", __name__)

ALL_ROLES = {
    "FacilityAdmin", "BoxOfficeOperator", "ProgramCoordinator", "EventsManager",
    "GroupSalesAgent", "MembershipClerk", "DevelopmentOfficer", "AccessibilityCoordinator",
}
VENUE_TYPES = {"DOME", "THEATER", "GALLERY", "CLASSROOM", "RENTAL_HALL"}


@bp.route("/venues", methods=["POST"])
def create_venue():
    _, role = authenticate()
    require_role(role, {"FacilityAdmin"})
    body = get_body()
    name = require_string(body, "name")
    venue_type = require_enum(body, "venue_type", VENUE_TYPES)
    seated_capacity = require_int(body, "seated_capacity")
    turnover = optional_int(body, "turnover_buffer_minutes", 15)
    accessible = optional_int(body, "accessible_seats", 0)

    # Field-range checks (ERR_VALIDATION, lowest priority).
    validate_range(seated_capacity >= 1, "seated_capacity must be >= 1")
    validate_range(turnover >= 0, "turnover_buffer_minutes must be >= 0")
    validate_range(accessible >= 0, "accessible_seats must be >= 0")
    validate_range(accessible <= seated_capacity,
                   "accessible_seats must not exceed seated_capacity")

    with db.lock:
        rec = new_record(with_version=True)
        rec.update({
            "name": name,
            "venue_type": venue_type,
            "seated_capacity": seated_capacity,
            "turnover_buffer_minutes": turnover,
            "accessible_seats": accessible,
            "status": "ACTIVE",
        })
        db.venues[rec["id"]] = rec
    return success(venue_view(rec), status=201)


@bp.route("/venues", methods=["GET"])
def list_venues():
    _, role = authenticate()
    require_role(role, ALL_ROLES)
    limit, offset = parse_pagination()
    venue_type = request.args.get("venue_type")
    with db.lock:
        records = list(db.venues.values())
        if venue_type is not None:
            records = [v for v in records if v["venue_type"] == venue_type]
        page, meta = paginate(records, limit, offset)
        data = [venue_view(v) for v in page]
    return success(data, status=200, pagination=meta)


@bp.route("/venues/<vid>", methods=["GET"])
def get_one_venue(vid):
    _, role = authenticate()
    require_role(role, {"FacilityAdmin", "BoxOfficeOperator", "ProgramCoordinator",
                        "EventsManager", "GroupSalesAgent"})
    with db.lock:
        v = get_venue(vid)
        return success(venue_view(v), status=200)


@bp.route("/venues/<vid>/shows", methods=["GET"])
def list_venue_shows(vid):
    _, role = authenticate()
    require_role(role, {"FacilityAdmin", "BoxOfficeOperator", "GroupSalesAgent"})
    limit, offset = parse_pagination()
    with db.lock:
        get_venue(vid)
        records = [s for s in db.shows.values() if s["venue_id"] == vid]
        page, meta = paginate(records, limit, offset)
        data = [show_view(s) for s in page]
    return success(data, status=200, pagination=meta)


@bp.route("/venues/<vid>/programs", methods=["GET"])
def list_venue_programs(vid):
    _, role = authenticate()
    require_role(role, {"FacilityAdmin", "ProgramCoordinator"})
    limit, offset = parse_pagination()
    with db.lock:
        get_venue(vid)
        records = [p for p in db.programs.values() if p["venue_id"] == vid]
        page, meta = paginate(records, limit, offset)
        data = [program_view(p) for p in page]
    return success(data, status=200, pagination=meta)


@bp.route("/venues/<vid>/rentals", methods=["GET"])
def list_venue_rentals(vid):
    _, role = authenticate()
    require_role(role, {"FacilityAdmin", "EventsManager"})
    limit, offset = parse_pagination()
    with db.lock:
        get_venue(vid)
        records = [r for r in db.rentals.values() if r["venue_id"] == vid]
        page, meta = paginate(records, limit, offset)
        data = [rental_view(r) for r in page]
    return success(data, status=200, pagination=meta)
