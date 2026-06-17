"""In-house assignment creation and reads (PRD §3.3, §2.8)."""
from flask import Blueprint, request

import db
import views
from db import new_full, touch
from errors import (
    ERR_CHAUFFEUR_DOUBLE_BOOKED,
    ERR_FORBIDDEN,
    ERR_FULFILLMENT_CONFLICT,
    ERR_INVALID_STATE,
    ERR_RESOURCE_UNAVAILABLE,
    ERR_STALE_VERSION,
    ERR_VEHICLE_TURNAROUND_VIOLATION,
    err,
)
from helpers import (
    as_int,
    as_str,
    floor_minutes,
    get_pagination,
    paginate,
    parse_dt,
    require_fields,
    sort_by_created,
)
from middleware import authenticate, require_role
from response import success
from routes.common import get_body, must_exist
from services.reservation_logic import active_assignment_for, open_farmout_for

bp = Blueprint("assignments", __name__)


def _windows_overlap_with_buffer(new_start, new_end, ex_start, ex_end, buffer_min):
    """Chauffeur one-sided rest-buffer conflict test (PRD §3.3 / calc chauffeur_overlap).

    conflict iff new_start < ex_end + buffer AND ex_start < new_end + buffer.
    Half-open windows; adjacency exactly at end+buffer is allowed.
    """
    from datetime import timedelta
    return (new_start < ex_end + timedelta(minutes=buffer_min)
            and ex_start < new_end + timedelta(minutes=buffer_min))


def _gap_minutes(window_a, window_b):
    """Whole-minute gap between two ordered windows (PRD §3.3 / calc vehicle_overlap)."""
    early, late = window_a, window_b
    return floor_minutes(late[0], early[1])  # late.start - early.end


@bp.route("/assignments", methods=["POST"])
def create_assignment():
    _, role = authenticate()
    require_role(role, ["Dispatcher"])
    body = get_body()
    require_fields(body, ["reservation_id", "chauffeur_id", "vehicle_id",
                          "expected_reservation_version"])
    reservation_id = as_str(body["reservation_id"], "reservation_id")
    chauffeur_id = as_str(body["chauffeur_id"], "chauffeur_id")
    vehicle_id = as_str(body["vehicle_id"], "vehicle_id")
    expected_version = as_int(body["expected_reservation_version"], "expected_reservation_version")

    # Existence of body FKs, left-to-right (PRD §2.5).
    reservation = must_exist(db.reservations, reservation_id, "Reservation")
    chauffeur = must_exist(db.chauffeurs, chauffeur_id, "Chauffeur")
    vehicle = must_exist(db.vehicles, vehicle_id, "Vehicle")

    # State: reservation CONFIRMED and IN_HOUSE (PRD §3.3, priority 7).
    if reservation["trip_status"] != "CONFIRMED":
        raise err(ERR_INVALID_STATE, "Reservation is not CONFIRMED")
    if reservation["fulfillment_mode"] != "IN_HOUSE":
        raise err(ERR_INVALID_STATE, "Reservation is not IN_HOUSE")

    # PRD §3.3 ordering: resource availability, chauffeur overlap, vehicle
    # turnaround, fulfillment-exclusivity, then version guard.

    # Resource availability: chauffeur not ON_TRIP/SUSPENDED (priority 10).
    if chauffeur["status"] in ("ON_TRIP", "SUSPENDED"):
        raise err(ERR_RESOURCE_UNAVAILABLE, "Chauffeur is unavailable")

    new_start = parse_dt(reservation["pickup_at"], "pickup_at")
    new_end = parse_dt(reservation["planned_drop_at"], "planned_drop_at")

    # Chauffeur overlap incl. rest_buffer_minutes (priority 11).
    rest_buffer = chauffeur["rest_buffer_minutes"]
    for a in db.assignments.values():
        if a["status"] != "ACTIVE" or a["chauffeur_id"] != chauffeur_id:
            continue
        ex_start = parse_dt(a["window_start_at"], "window_start_at")
        ex_end = parse_dt(a["window_end_at"], "window_end_at")
        if _windows_overlap_with_buffer(new_start, new_end, ex_start, ex_end, rest_buffer):
            raise err(ERR_CHAUFFEUR_DOUBLE_BOOKED, "Chauffeur window conflict")

    # Vehicle turnaround gap (priority 12).
    turnaround = vehicle["turnaround_minutes"]
    new_window = (new_start, new_end)
    for a in db.assignments.values():
        if a["status"] != "ACTIVE" or a["vehicle_id"] != vehicle_id:
            continue
        ex_start = parse_dt(a["window_start_at"], "window_start_at")
        ex_end = parse_dt(a["window_end_at"], "window_end_at")
        ex_window = (ex_start, ex_end)
        # order the two windows by start, ties by created_at (PRD §3.3).
        if (ex_start, a["created_at"]) <= (new_start, reservation["created_at"]):
            early, late = ex_window, new_window
        else:
            early, late = new_window, ex_window
        gap = floor_minutes(late[0], early[1])
        if gap < turnaround:
            raise err(ERR_VEHICLE_TURNAROUND_VIOLATION, "Vehicle turnaround conflict")

    # Fulfillment-exclusivity (priority 13).
    if active_assignment_for(reservation_id) is not None or open_farmout_for(reservation_id) is not None:
        raise err(ERR_FULFILLMENT_CONFLICT, "Reservation already has a fulfillment commitment")

    # Version guard (priority 16, PRD §2.8).
    if expected_version != reservation["version"]:
        raise err(ERR_STALE_VERSION, "Stale reservation version")

    # Create the assignment (PRD §3.3).
    assignment = new_full({
        "reservation_id": reservation_id,
        "chauffeur_id": chauffeur_id,
        "vehicle_id": vehicle_id,
        "window_start_at": reservation["pickup_at"],
        "window_end_at": reservation["planned_drop_at"],
        "status": "ACTIVE",
    })
    db.assignments[assignment["id"]] = assignment

    # Cascade hop 1: reservation CONFIRMED -> ASSIGNED, version++ (PRD §3.3).
    reservation["trip_status"] = "ASSIGNED"
    touch(reservation)

    # Cascade hop: chauffeur OFF_DUTY -> ON_DUTY (already ON_DUTY stays) (PRD §3.3).
    if chauffeur["status"] == "OFF_DUTY":
        chauffeur["status"] = "ON_DUTY"
        touch(chauffeur)

    return success(views.assignment(assignment), status=201)


@bp.route("/assignments/<assignment_id>", methods=["GET"])
def get_assignment(assignment_id):
    user_id, role = authenticate()
    require_role(role, ["DispatchAdmin", "Dispatcher", "Chauffeur"])
    rec = must_exist(db.assignments, assignment_id, "Assignment")
    if role == "Chauffeur" and rec["chauffeur_id"] != user_id:
        raise err(ERR_FORBIDDEN, "Chauffeur may only read their own assignments")
    return success(views.assignment(rec))


@bp.route("/assignments", methods=["GET"])
def list_assignments():
    user_id, role = authenticate()
    require_role(role, ["DispatchAdmin", "Dispatcher", "Chauffeur"])
    limit, offset = get_pagination(request.args)
    items = list(db.assignments.values())
    res_filter = request.args.get("reservation_id")
    chf_filter = request.args.get("chauffeur_id")
    veh_filter = request.args.get("vehicle_id")
    if res_filter is not None:
        items = [a for a in items if a["reservation_id"] == res_filter]
    if chf_filter is not None:
        items = [a for a in items if a["chauffeur_id"] == chf_filter]
    if veh_filter is not None:
        items = [a for a in items if a["vehicle_id"] == veh_filter]
    # A Chauffeur only sees their own assignments (PRD §2.1).
    if role == "Chauffeur":
        items = [a for a in items if a["chauffeur_id"] == user_id]
    items = sort_by_created(items)
    window, pagination = paginate(items, limit, offset)
    return success([views.assignment(a) for a in window], pagination=pagination)
