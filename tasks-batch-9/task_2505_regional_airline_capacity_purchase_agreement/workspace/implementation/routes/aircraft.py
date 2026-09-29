"""Fleet registration, induction and renewal (PRD 3.3)."""

from flask import Blueprint

import derive
import enums
import lookup
import validate
from auth import (ROLE_CPA_ADMINISTRATOR, ROLE_REGIONAL_OPS_CONTROLLER, any_role,
                  require)
from core import clock
from db import new_entity, public, store, touch
from errors import fail
from response import object_response
from routes.common import collection_listing, guard_state, guard_terminal

bp = Blueprint("aircraft", __name__)

LIST_FILTERS = (
    ("agreement_id", "agreement_id", None),
    ("assigned_base_id", "assigned_base_id", None),
    ("status", "status", enums.AIRCRAFT_STATUS),
)


def _base_of(tail):
    return store.crew_bases[tail["assigned_base_id"]]


@bp.route("/aircraft", methods=["POST"])
@require(ROLE_REGIONAL_OPS_CONTROLLER)
def register_aircraft():
    data = validate.body()
    agreement_id = validate.string_field(data, "agreement_id")
    agreement = lookup.reference("agreements", agreement_id)
    assigned_base_id = validate.string_field(data, "assigned_base_id")
    base = lookup.reference("crew_bases", assigned_base_id)

    tail_number = validate.string_field(data, "tail_number")
    seat_count = validate.int_field(data, "seat_count", minimum=1)
    ownership = validate.enum_field(data, "ownership", enums.OWNERSHIP)

    for tail in store.aircraft.values():
        if (tail["agreement_id"] == agreement["id"]
                and tail["tail_number"] == tail_number):
            fail("ERR_DUPLICATE_RESOURCE")

    tail = new_entity({
        "agreement_id": agreement["id"],
        "assigned_base_id": base["id"],
        "tail_number": tail_number,
        "seat_count": seat_count,
        "ownership": ownership,
        "status": "PENDING_INDUCTION",
        "transition_reason": None,
        "target_ownership": None,
        "grounded_reason": None,
        "inducted_at": None,
    })
    store.aircraft[tail["id"]] = tail
    return object_response(public(tail), 201)


@bp.route("/aircraft", methods=["GET"])
@any_role()
def list_aircraft():
    return collection_listing("aircraft", LIST_FILTERS)


@bp.route("/aircraft/<aircraft_id>", methods=["GET"])
@any_role()
def read_aircraft(aircraft_id):
    return object_response(public(lookup.aircraft(aircraft_id)))


@bp.route("/aircraft/<aircraft_id>/induct", methods=["POST"])
@require(ROLE_REGIONAL_OPS_CONTROLLER)
def induct_aircraft(aircraft_id):
    tail = lookup.aircraft(aircraft_id)
    agreement = store.agreements[tail["agreement_id"]]
    if agreement["status"] != "ACTIVE":
        fail("ERR_AGREEMENT_NOT_ACTIVE")

    guard_terminal(tail, enums.AIRCRAFT_TERMINAL)
    guard_state(tail["status"] == "PENDING_INDUCTION")

    base = _base_of(tail)
    guard_state(base["lifecycle_status"] == "ACTIVE",
                "The assigned crew base is CLOSED")

    prospective = base["assigned_aircraft_count"] + 1
    if prospective * base["pilots_required_per_aircraft"] > \
            base["line_qualified_pilot_count"]:
        fail("ERR_BASE_UNDERSTAFFED")
    if prospective > base["aircraft_allocation_cap"]:
        fail("ERR_FLEET_ALLOCATION_EXCEEDED")

    tail["status"] = "IN_SERVICE"
    tail["inducted_at"] = clock.iso()
    touch(tail)
    derive.apply_base_staffing(base)

    return object_response(public(tail))


@bp.route("/aircraft/<aircraft_id>/transition", methods=["POST"])
@require(ROLE_CPA_ADMINISTRATOR)
def transition_aircraft(aircraft_id):
    tail = lookup.aircraft(aircraft_id)
    data = validate.body()
    transition_reason = validate.enum_field(data, "transition_reason",
                                            enums.TRANSITION_REASON)
    target_ownership = validate.enum_field(data, "target_ownership", enums.OWNERSHIP)

    guard_terminal(tail, enums.AIRCRAFT_TERMINAL)
    guard_state(tail["status"] in ("IN_SERVICE", "GROUNDED_STAFFING"))

    open_leg = any(leg["aircraft_id"] == tail["id"] and leg["status"] == "SCHEDULED"
                   for leg in store.flight_legs.values())
    if open_leg:
        fail("ERR_AIRCRAFT_HAS_OPEN_LEGS")

    tail["status"] = "TRANSITION_PENDING"
    tail["transition_reason"] = transition_reason
    tail["target_ownership"] = target_ownership
    tail["grounded_reason"] = None
    touch(tail)
    derive.apply_base_staffing(_base_of(tail))

    return object_response(public(tail))


@bp.route("/aircraft/<aircraft_id>/complete-transition", methods=["POST"])
@require(ROLE_CPA_ADMINISTRATOR)
def complete_transition(aircraft_id):
    tail = lookup.aircraft(aircraft_id)

    guard_terminal(tail, enums.AIRCRAFT_TERMINAL)
    guard_state(tail["status"] == "TRANSITION_PENDING")

    tail["status"] = "TRANSITIONED"
    tail["ownership"] = tail["target_ownership"]
    touch(tail)
    return object_response(public(tail))
