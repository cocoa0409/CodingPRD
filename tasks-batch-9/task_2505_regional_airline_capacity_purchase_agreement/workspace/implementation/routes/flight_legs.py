"""Flight legs: scheduling, completion, cancellation and reinstatement (PRD 3.4)."""

from datetime import timedelta

from flask import Blueprint

import calc
import derive
import enums
import lookup
import validate
from auth import (ROLE_MAINLINE_SCHEDULER, ROLE_REGIONAL_OPS_CONTROLLER, any_role,
                  require)
from core import ZERO2, dec, round3
from db import new_entity, public, store, touch, values
from errors import fail
from response import object_response
from routes.common import collection_listing, guard_state, guard_terminal

bp = Blueprint("flight_legs", __name__)

LIST_FILTERS = (
    ("cycle_id", "cycle_id", None),
    ("aircraft_id", "aircraft_id", None),
    ("captain_pilot_id", "captain_pilot_id", None),
    ("status", "status", enums.LEG_STATUS),
)

TURN_BUFFER = timedelta(minutes=calc.AIRCRAFT_MIN_TURN_MINUTES)
GRACE = timedelta(minutes=calc.ON_TIME_GRACE_MINUTES)
DUTY_WINDOW = timedelta(hours=calc.PILOT_ROLLING_WINDOW_HOURS)

ACTIVE_LEG_STATUSES = ("SCHEDULED", "COMPLETED")


def _departure(leg):
    return leg["_scheduled_departure_dt"]


def _arrival(leg):
    return leg["_scheduled_arrival_dt"]


def _cycle_of(leg):
    return store.schedule_cycles[leg["cycle_id"]]


def _aircraft_of(leg):
    return store.aircraft[leg["aircraft_id"]]


def _agreement_of_cycle(cycle):
    return store.agreements[cycle["agreement_id"]]


def _active_claim(leg_id):
    """The leg's live cancellation claim: the newest one that is not VOIDED."""
    claims = [claim for claim in values(store.cancellation_claims)
              if claim["leg_id"] == leg_id and claim["status"] != "VOIDED"]
    return claims[-1] if claims else None


@bp.route("/flight-legs", methods=["POST"])
@require(ROLE_MAINLINE_SCHEDULER)
def schedule_leg():
    data = validate.body()
    cycle_id = validate.string_field(data, "cycle_id")
    cycle = lookup.reference("schedule_cycles", cycle_id)
    aircraft_id = validate.string_field(data, "aircraft_id")
    tail = lookup.reference("aircraft", aircraft_id)
    captain_pilot_id = validate.string_field(data, "captain_pilot_id")
    captain = lookup.reference("pilots", captain_pilot_id)

    flight_number = validate.string_field(data, "flight_number")
    origin = validate.string_field(data, "origin")
    destination = validate.string_field(data, "destination")
    scheduled_departure_utc, departure_dt = validate.datetime_field(
        data, "scheduled_departure_utc")
    scheduled_arrival_utc, arrival_dt = validate.datetime_field(
        data, "scheduled_arrival_utc")
    planned_block_hours = validate.hours_field(data, "planned_block_hours")

    guard_state(cycle["status"] == "OPEN",
                "The settlement month is not OPEN for scheduling")

    if tail["status"] != "IN_SERVICE":
        fail("ERR_AIRCRAFT_NOT_AVAILABLE")
    if captain["status"] != "LINE_QUALIFIED":
        fail("ERR_PILOT_NOT_QUALIFIED")

    captain_base = store.crew_bases[captain["base_id"]]
    if (tail["agreement_id"] != cycle["agreement_id"]
            or captain_base["agreement_id"] != cycle["agreement_id"]):
        fail("ERR_CROSS_AGREEMENT_REFERENCE")

    if arrival_dt <= departure_dt:
        fail("ERR_INVALID_INTERVAL")

    # Aircraft turn buffer — pairwise geometry, inclusive at exactly 35 minutes.
    for other in store.flight_legs.values():
        if other["aircraft_id"] != tail["id"]:
            continue
        if other["status"] not in ACTIVE_LEG_STATUSES:
            continue
        separated = (departure_dt >= _arrival(other) + TURN_BUFFER
                     or arrival_dt + TURN_BUFFER <= _departure(other))
        if not separated:
            fail("ERR_AIRCRAFT_TURN_CONFLICT")

    # Captain rolling duty cap — aggregate capacity over a half-open +/-24h window.
    window_start = departure_dt - DUTY_WINDOW
    window_end = departure_dt + DUTY_WINDOW
    total = dec(planned_block_hours)
    for other in store.flight_legs.values():
        if other["captain_pilot_id"] != captain["id"]:
            continue
        if other["status"] not in ACTIVE_LEG_STATUSES:
            continue
        other_departure = _departure(other)
        if window_start <= other_departure < window_end:
            total += other["planned_block_hours"]
    if round3(total) > calc.PILOT_ROLLING_BLOCK_CAP_HOURS:
        fail("ERR_PILOT_DUTY_CAP_EXCEEDED")

    leg = new_entity({
        "cycle_id": cycle["id"],
        "aircraft_id": tail["id"],
        "captain_pilot_id": captain["id"],
        "flight_number": flight_number,
        "origin": origin,
        "destination": destination,
        "scheduled_departure_utc": scheduled_departure_utc,
        "scheduled_arrival_utc": scheduled_arrival_utc,
        "planned_block_hours": planned_block_hours,
        "actual_block_hours": None,
        "actual_arrival_utc": None,
        "enplaned_bags": 0,
        "mishandled_bags": 0,
        "status": "SCHEDULED",
        "on_time": False,
        "leg_variable_payment_usd": ZERO2,
        "cancel_cause_code": None,
        "reinstate_count": 0,
        "_scheduled_departure_dt": departure_dt,
        "_scheduled_arrival_dt": arrival_dt,
    })
    store.flight_legs[leg["id"]] = leg

    derive.refresh_cycle(cycle)

    return object_response(public(leg), 201)


@bp.route("/flight-legs", methods=["GET"])
@any_role()
def list_legs():
    return collection_listing("flight_legs", LIST_FILTERS)


@bp.route("/flight-legs/<leg_id>", methods=["GET"])
@any_role()
def read_leg(leg_id):
    return object_response(public(lookup.flight_leg(leg_id)))


@bp.route("/flight-legs/<leg_id>/complete", methods=["POST"])
@require(ROLE_REGIONAL_OPS_CONTROLLER)
def complete_leg(leg_id):
    leg = lookup.flight_leg(leg_id)
    data = validate.body()
    actual_block_hours = validate.hours_field(data, "actual_block_hours")
    actual_arrival_utc, actual_arrival_dt = validate.datetime_field(
        data, "actual_arrival_utc")
    enplaned_bags = validate.int_field(data, "enplaned_bags")
    mishandled_bags = validate.int_field(data, "mishandled_bags")

    guard_terminal(leg, enums.LEG_TERMINAL)
    guard_state(leg["status"] == "SCHEDULED")
    cycle = _cycle_of(leg)
    guard_state(cycle["status"] == "OPEN", "The settlement month is not OPEN")

    tail = _aircraft_of(leg)
    if tail["status"] != "IN_SERVICE":
        fail("ERR_AIRCRAFT_NOT_AVAILABLE")

    if actual_arrival_dt <= _departure(leg):
        fail("ERR_INVALID_INTERVAL")

    agreement = _agreement_of_cycle(cycle)
    leg["actual_block_hours"] = actual_block_hours
    leg["actual_arrival_utc"] = actual_arrival_utc
    leg["_actual_arrival_dt"] = actual_arrival_dt
    leg["enplaned_bags"] = enplaned_bags
    leg["mishandled_bags"] = mishandled_bags
    leg["status"] = "COMPLETED"
    leg["on_time"] = actual_arrival_dt <= _arrival(leg) + GRACE
    leg["leg_variable_payment_usd"] = calc.leg_variable_amount(actual_block_hours,
                                                               agreement)
    touch(leg)

    derive.refresh_cycle(cycle)

    return object_response(public(leg))


@bp.route("/flight-legs/<leg_id>/cancel", methods=["POST"])
@require(ROLE_REGIONAL_OPS_CONTROLLER)
def cancel_leg(leg_id):
    leg = lookup.flight_leg(leg_id)
    data = validate.body()
    cause_code = validate.enum_field(data, "cause_code", enums.CANCEL_CAUSE_CODE)

    guard_terminal(leg, enums.LEG_TERMINAL)
    guard_state(leg["status"] == "SCHEDULED")
    cycle = _cycle_of(leg)
    guard_state(cycle["status"] == "OPEN", "The settlement month is not OPEN")

    cancelled = (cycle["cancelled_controllable_count"]
                 + cycle["cancelled_uncontrollable_count"])
    if cancelled + 1 > cycle["published_departures"]:
        fail("ERR_DEPARTURE_LEDGER_OVERFLOW")

    leg["status"] = "CANCELLED"
    leg["cancel_cause_code"] = cause_code
    touch(leg)

    claim = new_entity({
        "leg_id": leg["id"],
        "cycle_id": cycle["id"],
        "cause_code": cause_code,
        "classification": None,
        "effective_classification": "CONTROLLABLE",
        "status": "OPEN",
        "dispute_round": 0,
        "dispute_note": None,
    })
    store.cancellation_claims[claim["id"]] = claim

    derive.refresh_cycle(cycle, cascade=True)

    return object_response(public(leg))


@bp.route("/flight-legs/<leg_id>/reinstate", methods=["POST"])
@require(ROLE_REGIONAL_OPS_CONTROLLER)
def reinstate_leg(leg_id):
    leg = lookup.flight_leg(leg_id)

    guard_terminal(leg, enums.LEG_TERMINAL)
    guard_state(leg["status"] == "CANCELLED")
    cycle = _cycle_of(leg)
    guard_state(cycle["status"] == "OPEN", "The settlement month is not OPEN")

    tail = _aircraft_of(leg)
    if tail["status"] != "IN_SERVICE":
        fail("ERR_AIRCRAFT_NOT_AVAILABLE")

    claim = _active_claim(leg["id"])
    if claim is not None and claim["status"] == "FINALIZED":
        fail("ERR_CLAIM_ALREADY_FINALIZED")

    leg["status"] = "SCHEDULED"
    leg["cancel_cause_code"] = None
    leg["reinstate_count"] += 1
    touch(leg)

    if claim is not None:
        claim["status"] = "VOIDED"
        touch(claim)

    derive.refresh_cycle(cycle, cascade=True)

    return object_response(public(leg))
