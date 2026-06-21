"""Leg lifecycle endpoints incl. the cyclic will-call return (PRD 3.5)."""
from flask import Blueprint

from clock import clock, now_iso
from db import db, touch
from errors import err
from helpers import get_json_body, require_number
from middleware import get_user_id, require_roles
from response import ok_object
from serializers import serialize
from services.calculations import (NOSHOW_SUSPEND_THRESHOLD, rate_for_modality,
                                    will_call_dwell_minutes)
from services.cascades import (eligibility_lapse_cascade, maybe_complete_trip,
                               release_active_assignment)
from services.eligibility import has_coverage_now

bp = Blueprint("legs", __name__)


def get_leg_or_404(leg_id):
    l = db.legs.get(leg_id)
    if l is None:
        raise err("ERR_NOT_FOUND", "Leg not found")
    return l


def _require_assigned_driver(leg):
    """Ownership (priority 6): acting Driver must be the trip's assigned_driver_id."""
    trip = db.trips[leg["trip_id"]]
    if trip.get("assigned_driver_id") != get_user_id():
        raise err("ERR_NOT_OWNER", "Acting driver is not the trip's assigned driver")
    return trip


def _outbound_leg(trip_id):
    for l in db.legs.values():
        if l["trip_id"] == trip_id and l["direction"] == "OUTBOUND":
            return l
    return None


@bp.route("/legs/<leg_id>", methods=["GET"])
def get_leg(leg_id):
    require_roles("Coordinator", "Broker", "Auditor", "Driver")
    return ok_object(serialize(get_leg_or_404(leg_id)))


@bp.route("/legs/<leg_id>/ready", methods=["POST"])
def leg_ready(leg_id):
    require_roles("Coordinator")
    leg = get_leg_or_404(leg_id)
    # State (priority 5): PENDING -> READY defined only for will-call RETURN legs.
    if not (leg["direction"] == "RETURN" and leg["is_will_call"]):
        raise err("ERR_INVALID_STATE", "Only a will-call RETURN leg can be readied")
    if leg["leg_status"] != "PENDING":
        raise err("ERR_INVALID_STATE", "Leg is not PENDING")
    # Priority 10: sequencing — trip IN_PROGRESS and OUTBOUND DROPPED_OFF.
    trip = db.trips[leg["trip_id"]]
    outbound = _outbound_leg(leg["trip_id"])
    if trip["trip_status"] != "IN_PROGRESS" or outbound is None or outbound["leg_status"] != "DROPPED_OFF":
        raise err("ERR_LEG_SEQUENCE_VIOLATION",
                  "Will-call return cannot be readied before outbound is dropped off")
    leg["leg_status"] = "READY"
    leg["ready_called_at"] = now_iso()
    touch(leg)
    return ok_object(serialize(leg))


@bp.route("/legs/<leg_id>/cancel-ready", methods=["POST"])
def leg_cancel_ready(leg_id):
    require_roles("Coordinator")
    leg = get_leg_or_404(leg_id)
    if not (leg["direction"] == "RETURN" and leg["is_will_call"]):
        raise err("ERR_INVALID_STATE", "Only a will-call RETURN leg can retract readiness")
    if leg["leg_status"] != "READY":
        raise err("ERR_INVALID_STATE", "Leg is not READY")
    leg["leg_status"] = "PENDING"
    leg["ready_called_at"] = None
    touch(leg)
    return ok_object(serialize(leg))


@bp.route("/legs/<leg_id>/depart", methods=["POST"])
def leg_depart(leg_id):
    require_roles("Driver")
    leg = get_leg_or_404(leg_id)
    trip = _require_assigned_driver(leg)

    if leg["direction"] == "OUTBOUND":
        # PENDING -> EN_ROUTE; promotes ASSIGNED trip to IN_PROGRESS.
        if leg["leg_status"] != "PENDING":
            raise err("ERR_INVALID_STATE", "Outbound leg is not PENDING")
        leg["leg_status"] = "EN_ROUTE"
        touch(leg)
        if trip["trip_status"] == "ASSIGNED":
            trip["trip_status"] = "IN_PROGRESS"
            touch(trip)
    else:
        # RETURN: will-call must be READY with ready_called_at set (sequencing).
        if leg["is_will_call"]:
            if leg["leg_status"] != "READY":
                # Departing a will-call RETURN still PENDING is a sequence violation.
                if leg["leg_status"] == "PENDING":
                    raise err("ERR_LEG_SEQUENCE_VIOLATION",
                              "Will-call return cannot depart before it is READY")
                raise err("ERR_INVALID_STATE", "Will-call return leg is not READY")
            if leg["ready_called_at"] is None:
                raise err("ERR_LEG_SEQUENCE_VIOLATION", "Will-call return has no ready_called_at")
        else:
            if leg["leg_status"] != "PENDING":
                raise err("ERR_INVALID_STATE", "Return leg is not PENDING")
        leg["leg_status"] = "EN_ROUTE"
        touch(leg)
    return ok_object(serialize(leg))


@bp.route("/legs/<leg_id>/arrive", methods=["POST"])
def leg_arrive(leg_id):
    require_roles("Driver")
    leg = get_leg_or_404(leg_id)
    _require_assigned_driver(leg)
    if leg["leg_status"] != "EN_ROUTE":
        raise err("ERR_INVALID_STATE", "Leg is not EN_ROUTE")
    leg["leg_status"] = "ARRIVED"
    leg["arrived_at"] = now_iso()
    touch(leg)
    return ok_object(serialize(leg))


@bp.route("/legs/<leg_id>/pickup", methods=["POST"])
def leg_pickup(leg_id):
    require_roles("Driver")
    leg = get_leg_or_404(leg_id)
    trip = _require_assigned_driver(leg)
    if leg["leg_status"] != "ARRIVED":
        raise err("ERR_INVALID_STATE", "Leg is not ARRIVED")
    leg["leg_status"] = "PICKED_UP"
    leg["picked_up_at"] = now_iso()
    # Will-call dwell computed at pickup (PRD 3.8).
    if leg["direction"] == "RETURN" and leg["is_will_call"] and leg["ready_called_at"] is not None:
        from helpers import parse_dt
        rate = rate_for_modality(trip["modality"])
        ready = parse_dt(leg["ready_called_at"])
        picked = parse_dt(leg["picked_up_at"])
        leg["dwell_minutes"] = will_call_dwell_minutes(rate, ready, picked)
    touch(leg)
    return ok_object(serialize(leg))


@bp.route("/legs/<leg_id>/dropoff", methods=["POST"])
def leg_dropoff(leg_id):
    require_roles("Driver")
    leg = get_leg_or_404(leg_id)
    trip = _require_assigned_driver(leg)
    if leg["leg_status"] != "PICKED_UP":
        raise err("ERR_INVALID_STATE", "Leg is not PICKED_UP")
    body = get_json_body()
    odometer = require_number(body, "odometer_loaded_miles")  # must be >= 0
    leg["leg_status"] = "DROPPED_OFF"
    leg["dropped_off_at"] = now_iso()
    leg["odometer_loaded_miles"] = odometer
    touch(leg)
    # Bubble up: complete the trip if all non-cancelled legs are dropped off.
    maybe_complete_trip(trip)
    return ok_object(serialize(leg))


@bp.route("/legs/<leg_id>/no-show", methods=["POST"])
def leg_no_show(leg_id):
    require_roles("Driver")
    leg = get_leg_or_404(leg_id)
    trip = _require_assigned_driver(leg)
    # State (priority 5): ARRIVED -> NO_SHOW defined only for OUTBOUND.
    if leg["direction"] != "OUTBOUND":
        raise err("ERR_INVALID_STATE", "No-show is only valid on the OUTBOUND leg")
    if leg["leg_status"] != "ARRIVED":
        raise err("ERR_INVALID_STATE", "Outbound leg is not ARRIVED")

    leg["leg_status"] = "NO_SHOW"
    touch(leg)
    # RETURN leg in {PENDING, READY} -> CANCELLED.
    for other in db.legs.values():
        if other["trip_id"] == trip["id"] and other["direction"] == "RETURN" \
                and other["leg_status"] in ("PENDING", "READY"):
            other["leg_status"] = "CANCELLED"
            touch(other)
    # trip IN_PROGRESS -> NO_SHOW; release assignment, free driver.
    trip["trip_status"] = "NO_SHOW"
    release_active_assignment(trip)
    touch(trip)
    # Strike accrual + possible auto-suspend (PRD 3.5).
    member = db.members[trip["member_id"]]
    member["noshow_strike_count"] += 1
    if member["noshow_strike_count"] >= NOSHOW_SUSPEND_THRESHOLD and \
            member["eligibility_status"] == "ELIGIBLE":
        member["eligibility_status"] = "SUSPENDED"
        eligibility_lapse_cascade(member)
    touch(member)
    return ok_object(serialize(leg))
