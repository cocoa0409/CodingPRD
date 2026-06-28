"""Rental routes + lifecycle (PRD §3.6)."""
from datetime import timedelta

from flask import Blueprint, request

import errors
from db import db
from middleware import get_identity, require_role
from response import success, list_success
from services import serialize, calc
from services.common import (
    new_record, get_body, get_or_404, paginate, touch, check_owner,
    req_str, opt_str,
)
from routes.time_slots import req_dt

bp = Blueprint("rentals", __name__)

READ_ROLES = {"GardenAdmin", "GardenStaff", "RentalCoordinator",
              "DevelopmentOfficer", "Visitor"}


def _rental_eligible(membership, venue, subtotal_cents):
    """PATRON-tier ACTIVE member with subtotal >= floor (PRD §3.6)."""
    if membership is None or membership["status"] != "ACTIVE":
        return False
    plan = db.membership_plans.get(membership["plan_id"])
    if plan is None or plan["tier"] != "PATRON":
        return False
    if subtotal_cents < calc.MEMBER_DISCOUNT_FLOOR_CENTS:
        return False
    return True


def _price(venue, membership, starts_at, ends_at):
    hours = calc.rental_hours(starts_at, ends_at)
    subtotal_cents = hours * venue["hourly_rate_cents"]
    eligible = _rental_eligible(membership, venue, subtotal_cents)
    return calc.rental_price_cents(
        starts_at, ends_at, venue["hourly_rate_cents"], eligible,
        venue["member_rental_discount_pct"])


@bp.route("/v1/rentals", methods=["POST"])
def create_rental():
    _, role = get_identity()
    require_role(role, {"Visitor", "RentalCoordinator"})
    body = get_body()
    garden_id = req_str(body, "garden_id")
    venue_id = req_str(body, "venue_id")
    starts_at = req_dt(body, "starts_at")
    ends_at = req_dt(body, "ends_at")
    membership_id = opt_str(body, "membership_id", "")

    get_or_404(db.gardens, garden_id)
    venue = get_or_404(db.venues, venue_id)
    membership = None
    if membership_id:
        membership = get_or_404(db.memberships, membership_id)

    if venue["garden_id"] != garden_id:
        raise errors.cross_garden_reference()
    if membership is not None and membership["garden_id"] != garden_id:
        raise errors.cross_garden_reference()

    # Time window well-formed (PRD §3.6).
    if ends_at <= starts_at:
        raise errors.invalid_window()

    quoted_cents = _price(venue, membership, starts_at, ends_at)

    rec = new_record({
        "garden_id": garden_id,
        "venue_id": venue_id,
        "membership_id": membership_id,
        "starts_at": starts_at,
        "ends_at": ends_at,
        "quoted_cents": quoted_cents,
        "final_cents": 0,
        "status": "REQUESTED",
    })
    db.rentals[rec["id"]] = rec
    return success(serialize.rental(rec), status=201)


@bp.route("/v1/rentals/<rental_id>", methods=["GET"])
def read_rental(rental_id):
    _, role = get_identity()
    require_role(role, READ_ROLES)
    rec = get_or_404(db.rentals, rental_id)
    return success(serialize.rental(rec), status=200)


@bp.route("/v1/rentals", methods=["GET"])
def list_rentals():
    _, role = get_identity()
    require_role(role, READ_ROLES)
    garden_id = request.args.get("garden_id")
    venue_id = request.args.get("venue_id")
    membership_id = request.args.get("membership_id")
    status = request.args.get("status")
    records = list(db.rentals.values())
    if garden_id is not None:
        records = [r for r in records if r["garden_id"] == garden_id]
    if venue_id is not None:
        records = [r for r in records if r["venue_id"] == venue_id]
    if membership_id is not None:
        records = [r for r in records if r["membership_id"] == membership_id]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    page, limit, offset, total = paginate(records)
    return list_success([serialize.rental(r) for r in page],
                        limit, offset, total)


@bp.route("/v1/rentals/<rental_id>/confirm", methods=["POST"])
def confirm_rental(rental_id):
    _, role = get_identity()
    require_role(role, {"RentalCoordinator"})
    rec = get_or_404(db.rentals, rental_id)
    if rec["status"] != "REQUESTED":
        raise errors.invalid_state()

    venue = db.venues.get(rec["venue_id"])
    # Venue overlap check with buffer (PRD §3.6).
    buffer = timedelta(minutes=venue["buffer_minutes"])
    for other in db.rentals.values():
        if other["id"] == rec["id"]:
            continue
        if other["venue_id"] != rec["venue_id"]:
            continue
        if other["status"] != "CONFIRMED":
            continue
        widened_start = other["starts_at"] - buffer
        widened_end = other["ends_at"] + buffer
        # Overlap of [widened_start, widened_end) with [rec.starts_at, rec.ends_at).
        if widened_start < rec["ends_at"] and rec["starts_at"] < widened_end:
            raise errors.venue_double_booked()

    membership = None
    if rec["membership_id"]:
        membership = db.memberships.get(rec["membership_id"])
    final_cents = _price(venue, membership, rec["starts_at"], rec["ends_at"])
    rec["final_cents"] = final_cents
    rec["status"] = "CONFIRMED"
    touch(rec)
    return success(serialize.rental(rec), status=200)


@bp.route("/v1/rentals/<rental_id>/reject", methods=["POST"])
def reject_rental(rental_id):
    _, role = get_identity()
    require_role(role, {"RentalCoordinator"})
    rec = get_or_404(db.rentals, rental_id)
    if rec["status"] != "REQUESTED":
        raise errors.invalid_state()
    rec["status"] = "REJECTED"
    touch(rec)
    return success(serialize.rental(rec), status=200)


@bp.route("/v1/rentals/<rental_id>/cancel", methods=["POST"])
def cancel_rental(rental_id):
    user_id, role = get_identity()
    require_role(role, {"Visitor", "RentalCoordinator"})
    rec = get_or_404(db.rentals, rental_id)
    check_owner(role, user_id, rec["membership_id"])
    if rec["status"] not in {"REQUESTED", "CONFIRMED"}:
        raise errors.invalid_state()
    rec["status"] = "CANCELLED"
    touch(rec)
    return success(serialize.rental(rec), status=200)
