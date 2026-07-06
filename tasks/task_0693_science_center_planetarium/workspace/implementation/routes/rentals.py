"""RentalEvent endpoints (PRD §3.7)."""
from flask import Blueprint, request

from db import db, new_record, touch
from clock import parse_iso, iso
from errors import (
    err,
    ERR_INVALID_REQUEST,
    ERR_VALIDATION,
    ERR_VENUE_TYPE_MISMATCH,
    ERR_INVALID_TIME_WINDOW,
    ERR_RENTAL_TIME_CONFLICT,
    ERR_INVALID_STATE,
)
from middleware import authenticate, require_role
from response import success
from services.common import (
    get_body,
    require_string,
    require_int,
    parse_pagination,
    paginate,
)
from services.lookups import get_venue, get_rental
from services.serialize import rental_view
from services.calculations import rental_deposit, rental_total

bp = Blueprint("rentals", __name__)


def _parse_dt(body, field):
    if field not in body or body[field] is None:
        raise err(ERR_INVALID_REQUEST, f"Missing required field: {field}")
    dt = parse_iso(body[field])
    if dt is None:
        raise err(ERR_INVALID_REQUEST, f"Field {field} is not a valid ISO8601 instant")
    return dt


@bp.route("/rentals", methods=["POST"])
def create_rental():
    _, role = authenticate()
    require_role(role, {"EventsManager"})
    body = get_body()
    require_string(body, "venue_id")
    venue_id = body["venue_id"]
    host_name = require_string(body, "host_name")
    starts_at = _parse_dt(body, "starts_at")
    ends_at = _parse_dt(body, "ends_at")
    guest_count = require_int(body, "guest_count")
    base_rental = require_int(body, "base_rental_cents")

    with db.lock:
        venue = get_venue(venue_id)
        # Venue-type compatibility (priority 11) before time-window (priority 12).
        if venue["venue_type"] != "RENTAL_HALL":
            raise err(ERR_VENUE_TYPE_MISMATCH, "Rental requires a RENTAL_HALL venue")
        # Time-window strictly-after (priority 12).
        if not (ends_at > starts_at):
            raise err(ERR_INVALID_TIME_WINDOW, "ends_at must be strictly after starts_at")
        # Field-range.
        if guest_count < 1:
            raise err(ERR_VALIDATION, "guest_count must be >= 1")
        if base_rental < 0:
            raise err(ERR_VALIDATION, "base_rental_cents must be >= 0")

        rec = new_record(with_version=True)
        deposit = rental_deposit({"base_rental_cents": base_rental}, guest_count)
        rec.update({
            "venue_id": venue_id,
            "host_name": host_name,
            "starts_at": iso(starts_at),
            "ends_at": iso(ends_at),
            "guest_count": guest_count,
            "actual_guest_count": None,
            "base_rental_cents": base_rental,
            "deposit_cents": deposit,
            "total_cents": None,
            "status": "INQUIRY",
            "_starts_at_dt": starts_at,
            "_ends_at_dt": ends_at,
        })
        db.rentals[rec["id"]] = rec
    return success(rental_view(rec), status=201)


@bp.route("/rentals", methods=["GET"])
def list_rentals():
    _, role = authenticate()
    require_role(role, {"EventsManager", "FacilityAdmin"})
    limit, offset = parse_pagination()
    venue_id = request.args.get("venue_id")
    status = request.args.get("status")
    with db.lock:
        records = list(db.rentals.values())
        if venue_id is not None:
            records = [r for r in records if r["venue_id"] == venue_id]
        if status is not None:
            records = [r for r in records if r["status"] == status]
        page, meta = paginate(records, limit, offset)
        data = [rental_view(r) for r in page]
    return success(data, status=200, pagination=meta)


@bp.route("/rentals/<rid>", methods=["GET"])
def get_one_rental(rid):
    _, role = authenticate()
    require_role(role, {"EventsManager"})
    with db.lock:
        r = get_rental(rid)
        return success(rental_view(r), status=200)


@bp.route("/rentals/<rid>/hold", methods=["POST"])
def hold_rental(rid):
    _, role = authenticate()
    require_role(role, {"EventsManager"})
    with db.lock:
        r = get_rental(rid)
        # State (priority 5): must be INQUIRY.
        if r["status"] != "INQUIRY":
            raise err(ERR_INVALID_STATE, "Rental is not in INQUIRY state")
        # Rental time conflict (priority 10): bare window (no buffer) must not
        # overlap any HELD/CONFIRMED rental in the same venue.
        for other in db.rentals.values():
            if other["id"] == r["id"]:
                continue
            if other["venue_id"] != r["venue_id"]:
                continue
            if other["status"] not in ("HELD", "CONFIRMED"):
                continue
            if r["_starts_at_dt"] < other["_ends_at_dt"] and other["_starts_at_dt"] < r["_ends_at_dt"]:
                raise err(ERR_RENTAL_TIME_CONFLICT, "Rental window overlaps an existing hold")
        r["status"] = "HELD"
        touch(r)
        return success(rental_view(r), status=200)


@bp.route("/rentals/<rid>/confirm", methods=["POST"])
def confirm_rental(rid):
    _, role = authenticate()
    require_role(role, {"EventsManager"})
    body = get_body()
    actual_guests = require_int(body, "actual_guest_count")
    with db.lock:
        r = get_rental(rid)
        if r["status"] != "HELD":
            raise err(ERR_INVALID_STATE, "Rental is not HELD")
        if actual_guests < 0:
            raise err(ERR_VALIDATION, "actual_guest_count must be >= 0")
        r["actual_guest_count"] = actual_guests
        r["total_cents"] = rental_total({"base_rental_cents": r["base_rental_cents"]}, actual_guests)
        r["status"] = "CONFIRMED"
        touch(r)
        return success(rental_view(r), status=200)


@bp.route("/rentals/<rid>/cancel", methods=["POST"])
def cancel_rental(rid):
    _, role = authenticate()
    require_role(role, {"EventsManager"})
    with db.lock:
        r = get_rental(rid)
        if r["status"] == "CONFIRMED":
            # Permitted only while clock < starts_at.
            if not (db.clock.now < r["_starts_at_dt"]):
                raise err(ERR_INVALID_STATE, "Rental has already started")
        elif r["status"] not in ("INQUIRY", "HELD"):
            raise err(ERR_INVALID_STATE, "Rental not in a cancellable state")
        r["status"] = "CANCELLED"
        touch(r)
        return success(rental_view(r), status=200)
