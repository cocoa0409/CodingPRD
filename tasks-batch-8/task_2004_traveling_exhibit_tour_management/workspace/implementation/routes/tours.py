"""Clock, Tour, Venue, and financial-summary endpoints."""

from flask import Blueprint

import db
import system
from envelope import ok_object
from errors import fail
from security import require_roles, ALL_ROLES
from serializers import tour_out, venue_out
from validate import (json_body, req_str, req_int, req_bool, req_dt,
                      get_tour, get_venue, paginate, apply_filters,
                      sorted_created)

bp = Blueprint("tours", __name__)


# --- logical clock (PRD §2.4) -------------------------------------------------

@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    require_roles("TourManager")
    data = json_body()
    to_iso = req_dt(data, "to_iso8601")
    to_dt = db.parse_dt(to_iso)
    system.clock_set(to_dt)
    return ok_object({"current_utc": db.iso_from_dt(to_dt)})


# --- tours ----------------------------------------------------------------------

@bp.route("/tours", methods=["POST"])
def create_tour():
    require_roles("TourManager")
    data = json_body()
    title = req_str(data, "title")
    exhibit_code = req_str(data, "exhibit_code")
    crate_count = req_int(data, "crate_count")
    declared_value = req_int(data, "declared_value_cents")
    gap_days = req_int(data, "refurbishment_gap_days", minimum=0)
    if any(t["exhibit_code"] == exhibit_code for t in db.tours.values()):
        fail("ERR_INVALID_REQUEST",
             "exhibit_code must be unique across all tours")
    tour = db.stamp_new({
        "id": db.new_id(),
        "title": title,
        "exhibit_code": exhibit_code,
        "crate_count": crate_count,
        "declared_value_cents": declared_value,
        "refurbishment_gap_days": gap_days,
        "status": "DRAFT",
        "total_billed_cents": 0,
        "total_collected_cents": 0,
        "total_waived_cents": 0,
    })
    db.tours[tour["id"]] = tour
    return ok_object(tour_out(tour), status=201)


@bp.route("/tours/<tour_id>", methods=["GET"])
def get_one_tour(tour_id):
    require_roles(*ALL_ROLES)
    return ok_object(tour_out(get_tour(tour_id)))


@bp.route("/tours", methods=["GET"])
def list_tours():
    require_roles(*ALL_ROLES)
    items = apply_filters(list(db.tours.values()), [("status", "status")])
    return paginate([tour_out(t) for t in sorted_created(items)])


@bp.route("/tours/<tour_id>/transition", methods=["POST"])
def tour_transition(tour_id):
    require_roles("TourManager")
    tour = get_tour(tour_id)
    data = json_body()
    action = data.get("action")
    if action not in ("OPEN_BOOKING", "RETIRE"):
        fail("ERR_INVALID_REQUEST", "Unrecognized action: %r" % action)

    if action == "OPEN_BOOKING":
        if tour["status"] != "DRAFT":
            fail("ERR_INVALID_STATE",
                 "OPEN_BOOKING is only permitted from DRAFT")
        if tour["crate_count"] <= 0 \
                or not any(c["tour_id"] == tour["id"] for c in db.crates.values()):
            fail("ERR_INVALID_STATE",
                 "Booking opens only with a positive crate_count and at least "
                 "one registered crate")
        tour["status"] = "BOOKING"
        db.touch(tour)
        return ok_object(tour_out(tour))

    # RETIRE
    if tour["status"] not in ("BOOKING", "ON_TOUR", "IN_REFURBISHMENT"):
        fail("ERR_INVALID_STATE",
             "RETIRE is only permitted from BOOKING, ON_TOUR, or "
             "IN_REFURBISHMENT")
    active = [s for s in system.stops_of_tour(tour["id"])
              if s["status"] in ("CONTRACTED", "INSTALLING", "OPEN", "TEARDOWN")]
    open_claims = [c for sh in system.shipments_of_tour(tour["id"])
                   for c in system.claims_of_shipment(sh["id"])
                   if c["status"] in system.OPEN_CLAIM_STATES]
    if active or open_claims:
        fail("ERR_TOUR_NOT_RETIREABLE",
             "Tour has committed stops or open damage claims")
    system.retire_tour(tour)
    return ok_object(tour_out(tour))


# --- venues ---------------------------------------------------------------------

@bp.route("/venues", methods=["POST"])
def create_venue():
    require_roles("TourManager")
    data = json_body()
    venue = db.stamp_new({
        "id": db.new_id(),
        "name": req_str(data, "name"),
        "city": req_str(data, "city"),
        "climate_controlled": req_bool(data, "climate_controlled"),
        "max_gallery_sqm": req_int(data, "max_gallery_sqm"),
        "local_sponsorship_cap_cents": req_int(data, "local_sponsorship_cap_cents"),
    })
    db.venues[venue["id"]] = venue
    return ok_object(venue_out(venue), status=201)


@bp.route("/venues/<venue_id>", methods=["GET"])
def get_one_venue(venue_id):
    require_roles(*ALL_ROLES)
    return ok_object(venue_out(get_venue(venue_id)))


# --- financial summary (PRD §3.9) -------------------------------------------------

@bp.route("/tours/<tour_id>/financial-summary", methods=["GET"])
def financial_summary(tour_id):
    require_roles(*ALL_ROLES)
    tour = get_tour(tour_id)
    billed = tour["total_billed_cents"]
    collected = tour["total_collected_cents"]
    return ok_object({
        "total_billed_cents": billed,
        "total_collected_cents": collected,
        "total_waived_cents": tour["total_waived_cents"],
        "outstanding_cents": billed - collected,
    })
