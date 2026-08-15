"""Tour endpoints (PRD §3.1)."""

from flask import Blueprint, request

from db import DB
from errors import (
    ERR_TOUR_NOT_FOUND,
    ERR_INVALID_TOUR_STATE,
    ERR_SHOWS_NOT_TERMINAL,
    ERR_STALE_VERSION,
    ERR_VALIDATION,
    err,
)
from middleware import (
    require_role,
    require_auth,
    get_json_body,
    require_string,
    require_int,
    require_bps,
    base_fields,
    touch,
    paginate,
)
from response import success_object, success_list
from services.core import validate_size_curve
from services.serializers import tour_view

bp = Blueprint("tours", __name__)

ALL_ROLES = ("TourManager", "Seller", "Accountant", "VenueRep")


def get_tour_or_404(tour_id):
    t = DB.tours.get(tour_id)
    if t is None:
        raise err(ERR_TOUR_NOT_FOUND, 404, "No Tour with the given id")
    return t


@bp.post("/merch/tours")
def create_tour():
    require_role("TourManager")
    body = get_json_body()
    name = require_string(body, "name", required=True)
    artist_name = require_string(body, "artist_name", required=True)
    standard_rate_bps = require_bps(body, "standard_rate_bps", required=True)
    tier_threshold_cents = require_int(body, "tier_threshold_cents", ge=0, required=True)
    tier_bonus_bps = require_bps(body, "tier_bonus_bps", required=True)
    licensed_flat_per_unit_cents = require_int(body, "licensed_flat_per_unit_cents", ge=0, required=True)
    licensed_rate_bps = require_bps(body, "licensed_rate_bps", required=True)

    curve = body.get("default_size_curve")
    if curve is None:
        curve = {"S": 1, "M": 2, "L": 2, "XL": 1}
    curve = validate_size_curve(curve)

    tolerance = require_int(body, "cash_variance_tolerance_cents", ge=0)
    if tolerance is None:
        tolerance = 1000

    tour = {
        **base_fields(),
        "name": name,
        "artist_name": artist_name,
        "default_size_curve": curve,
        "cash_variance_tolerance_cents": tolerance,
        "standard_rate_bps": standard_rate_bps,
        "tier_threshold_cents": tier_threshold_cents,
        "tier_bonus_bps": tier_bonus_bps,
        "licensed_flat_per_unit_cents": licensed_flat_per_unit_cents,
        "licensed_rate_bps": licensed_rate_bps,
        "status": "PLANNING",
    }
    DB.tours[tour["id"]] = tour
    return success_object(tour_view(tour), status=201)


@bp.get("/merch/tours")
def list_tours():
    require_auth()
    items = sorted(DB.tours.values(), key=lambda t: t["created_at"])
    page, limit, offset, total = paginate(items)
    return success_list([tour_view(t) for t in page], limit, offset, total)


@bp.get("/merch/tours/<tour_id>")
def get_tour(tour_id):
    require_auth()
    tour = get_tour_or_404(tour_id)
    return success_object(tour_view(tour))


@bp.post("/merch/tours/<tour_id>/activate")
def activate_tour(tour_id):
    require_role("TourManager")
    tour = get_tour_or_404(tour_id)
    if tour["status"] != "PLANNING":
        raise err(ERR_INVALID_TOUR_STATE, 409, "Only a PLANNING tour can be activated")
    tour["status"] = "ACTIVE"
    touch(tour)
    return success_object(tour_view(tour))


@bp.post("/merch/tours/<tour_id>/close")
def close_tour(tour_id):
    require_role("TourManager")
    tour = get_tour_or_404(tour_id)
    if tour["status"] != "ACTIVE":
        raise err(ERR_INVALID_TOUR_STATE, 409, "Only an ACTIVE tour can be closed")
    for show in DB.shows.values():
        if show["tour_id"] == tour_id and show["status"] not in ("CLOSED", "CANCELLED"):
            raise err(ERR_SHOWS_NOT_TERMINAL, 409,
                      "Every show of the tour must be CLOSED or CANCELLED")
    tour["status"] = "CLOSED"
    touch(tour)
    return success_object(tour_view(tour))


@bp.patch("/merch/tours/<tour_id>/royalty-config")
def patch_royalty_config(tour_id):
    require_role("TourManager")
    tour = get_tour_or_404(tour_id)
    body = get_json_body()

    # State gate before OCC (PRD §2.7 order: state, then staleness).
    if tour["status"] == "CLOSED":
        from errors import ERR_ALREADY_TERMINAL
        raise err(ERR_ALREADY_TERMINAL, 409, "Cannot write to a CLOSED tour")

    # OCC staleness (priority 5 in PRD §2.7) precedes body shape checks (12).
    expected = body.get("expected_tour_version")
    if expected is not None and isinstance(expected, int) and not isinstance(expected, bool):
        if expected != tour["version"]:
            raise err(ERR_STALE_VERSION, 412,
                      "expected_tour_version does not match the tour's current version")

    new_std = require_bps(body, "standard_rate_bps", required=True)
    new_threshold = require_int(body, "tier_threshold_cents", ge=0, required=True)
    new_bonus = require_bps(body, "tier_bonus_bps", required=True)
    new_flat = require_int(body, "licensed_flat_per_unit_cents", ge=0, required=True)
    new_rate = require_bps(body, "licensed_rate_bps", required=True)

    if expected is None or not isinstance(expected, int) or isinstance(expected, bool):
        raise err(ERR_VALIDATION, 400, "expected_tour_version is required and must be an integer")

    tour["standard_rate_bps"] = new_std
    tour["tier_threshold_cents"] = new_threshold
    tour["tier_bonus_bps"] = new_bonus
    tour["licensed_flat_per_unit_cents"] = new_flat
    tour["licensed_rate_bps"] = new_rate
    touch(tour)
    return success_object(tour_view(tour))
