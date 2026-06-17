"""Flight tracking creation and updates with run-late propagation (PRD §3.6)."""
from datetime import timedelta

from flask import Blueprint

import db
import views
from db import new_full, touch
from errors import (
    ERR_FLIGHT_NOT_APPLICABLE,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    err,
)
from helpers import (
    as_bool,
    as_str,
    floor_minutes,
    format_dt,
    parse_dt,
    require_fields,
)
from middleware import authenticate, require_role
from response import success
from routes.common import get_body, must_exist
from services.calc import FLIGHT_DELAY_THRESHOLD_MIN
from services.reservation_logic import active_assignment_for

bp = Blueprint("flights", __name__)


@bp.route("/flight-trackings", methods=["POST"])
def create_flight_tracking():
    user_id, role = authenticate()
    require_role(role, ["Dispatcher", "CorporateBooker"])
    body = get_body()
    require_fields(body, ["reservation_id", "flight_number", "scheduled_arrival_at"])
    reservation_id = as_str(body["reservation_id"], "reservation_id")
    flight_number = as_str(body["flight_number"], "flight_number")
    scheduled_raw = as_str(body["scheduled_arrival_at"], "scheduled_arrival_at")
    meet_and_greet = body.get("meet_and_greet", False)
    if meet_and_greet is None:
        meet_and_greet = False
    meet_and_greet = as_bool(meet_and_greet, "meet_and_greet")
    parse_dt(scheduled_raw, "scheduled_arrival_at")  # validate shape

    reservation = must_exist(db.reservations, reservation_id, "Reservation")

    # Booker may only attach to its own account's reservation (PRD §2.1).
    if role == "CorporateBooker" and reservation["corporate_account_id"] != user_id:
        from errors import ERR_FORBIDDEN
        raise err(ERR_FORBIDDEN, "Booker may only act on its own reservations")

    # AIRPORT only, at most one per reservation (PRD §3.6, priority 8).
    if reservation["trip_type"] != "AIRPORT":
        raise err(ERR_FLIGHT_NOT_APPLICABLE, "Flight tracking only applies to AIRPORT trips")
    for ft in db.flight_trackings.values():
        if ft["reservation_id"] == reservation_id:
            raise err(ERR_FLIGHT_NOT_APPLICABLE, "Reservation already has flight tracking")

    rec = new_full({
        "reservation_id": reservation_id,
        "flight_number": flight_number,
        "scheduled_arrival_at": scheduled_raw,
        "estimated_arrival_at": scheduled_raw,
        "meet_and_greet": meet_and_greet,
        "status": "ON_TIME",
        "_applied_shift_minutes": 0,
    })
    db.flight_trackings[rec["id"]] = rec
    return success(views.flight_tracking(rec), status=201)


@bp.route("/flight-trackings/<flight_id>/flight-updates", methods=["POST"])
def flight_update(flight_id):
    _, role = authenticate()
    require_role(role, ["DispatchAdmin", "Dispatcher"])
    flight = must_exist(db.flight_trackings, flight_id, "FlightTracking")
    body = get_body()

    kind = body.get("kind")
    est_raw = body.get("estimated_arrival_at")
    if kind is None and est_raw is None:
        raise err(ERR_INVALID_REQUEST, "An update needs estimated_arrival_at or kind")

    scheduled = parse_dt(flight["scheduled_arrival_at"], "scheduled_arrival_at")

    # LANDED finalizes: set status + estimated_arrival_at, no window shift (PRD §3.6).
    if kind == "LANDED":
        if est_raw is not None:
            est_raw = as_str(est_raw, "estimated_arrival_at")
            parse_dt(est_raw, "estimated_arrival_at")
            flight["estimated_arrival_at"] = est_raw
        flight["status"] = "LANDED"
        touch(flight)
        return success(views.flight_tracking(flight))

    if kind is not None:
        raise err(ERR_INVALID_REQUEST, "Unknown flight update kind")

    # Non-landing update: estimated_arrival_at drives ON_TIME <-> DELAYED.
    est_raw = as_str(est_raw, "estimated_arrival_at")
    estimated = parse_dt(est_raw, "estimated_arrival_at")
    flight["estimated_arrival_at"] = est_raw

    delay_minutes = floor_minutes(estimated, scheduled)
    assignment = _propagation_assignment(flight["reservation_id"])
    prior = flight.get("_applied_shift_minutes", 0)

    if delay_minutes > FLIGHT_DELAY_THRESHOLD_MIN:
        flight["status"] = "DELAYED"
        if assignment is not None:
            shift = delay_minutes - prior
            _shift_window(assignment, shift)
            flight["_applied_shift_minutes"] = delay_minutes
    else:
        # within threshold -> ON_TIME; revert any prior shift (PRD §3.6).
        flight["status"] = "ON_TIME"
        if assignment is not None and prior != 0:
            _shift_window(assignment, -prior)
        flight["_applied_shift_minutes"] = 0

    touch(flight)
    return success(views.flight_tracking(flight))


def _propagation_assignment(reservation_id):
    """The single ACTIVE assignment for an ASSIGNED reservation, else None.

    Run-late propagation only applies when the linked reservation is ASSIGNED
    with exactly one ACTIVE assignment (PRD §3.6).
    """
    reservation = db.reservations.get(reservation_id)
    if reservation is None or reservation["trip_status"] != "ASSIGNED":
        return None
    actives = [a for a in db.assignments.values()
               if a["reservation_id"] == reservation_id and a["status"] == "ACTIVE"]
    if len(actives) != 1:
        return None
    return actives[0]


def _shift_window(assignment, minutes):
    start = parse_dt(assignment["window_start_at"], "window_start_at")
    end = parse_dt(assignment["window_end_at"], "window_end_at")
    assignment["window_start_at"] = format_dt(start + timedelta(minutes=minutes))
    assignment["window_end_at"] = format_dt(end + timedelta(minutes=minutes))
    touch(assignment)
