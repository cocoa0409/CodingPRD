"""Unit reads and the dispatch state machine (PRD 3.1)."""

from flask import Blueprint

from constants import (
    ALLOWED_DISPATCH_MOVES,
    API_PREFIX,
    CONTROL_STATUSES,
    DISPATCH_STATES,
    FUEL_TYPES,
    ROLE_FACILITY_OPERATOR,
)
from db import db, public, public_list, sort_rows, touch
from errors import fail
from lookup import facility_of_unit, find, get, outages_of_unit
from middleware import ANY_ROLE, authenticate, enforce_facility_scope
from response import array_response, object_response
from validation import (
    apply_pagination,
    body_dict,
    enum_field,
    match_filters,
    pagination,
    query_filters,
)

bp = Blueprint("units", __name__)


@bp.route(API_PREFIX + "/units", methods=["GET"])
def list_units():
    authenticate(ANY_ROLE)
    filters = query_filters(
        {
            "facility_id": "str",
            "dispatch_state": DISPATCH_STATES,
            "control_status": CONTROL_STATUSES,
            "dispatch_restricted": "bool",
            "primary_fuel": FUEL_TYPES,
        }
    )
    limit, offset = pagination()
    rows = match_filters(list(db.units.values()), filters)
    rows = sort_rows(rows)
    return array_response(
        public_list(apply_pagination(rows, limit, offset)), limit, offset, len(rows)
    )


@bp.route(API_PREFIX + "/units/<unit_id>", methods=["GET"])
def read_unit(unit_id):
    authenticate(ANY_ROLE)
    unit = get("unit", unit_id)
    return object_response(public(unit))


@bp.route(API_PREFIX + "/units/<unit_id>/dispatch", methods=["PATCH"])
def change_dispatch(unit_id):
    caller = authenticate((ROLE_FACILITY_OPERATOR,))
    body = body_dict()
    enforce_facility_scope(caller, facility_of_unit(find("unit", unit_id)))

    target = enum_field(body, "dispatch_state", DISPATCH_STATES, required=True)
    unit = get("unit", unit_id)

    current = unit["dispatch_state"]
    # Exactly four moves are declared; restating the current position is not one.
    if (current, target) not in ALLOWED_DISPATCH_MOVES:
        fail(
            "ERR_INVALID_STATE_TRANSITION",
            "Dispatch move %s -> %s is not permitted." % (current, target),
        )

    if target == "ONLINE":
        if unit["dispatch_restricted"]:
            fail(
                "ERR_INVALID_STATE_TRANSITION",
                "A dispatch-restricted unit may not be brought ONLINE.",
            )
        for outage in outages_of_unit(unit["id"]):
            if outage["status"] == "ACTIVE" and outage["outage_type"] == "PLANNED_MAINTENANCE":
                fail(
                    "ERR_INVALID_STATE_TRANSITION",
                    "An active planned-maintenance outage blocks going ONLINE.",
                )

    unit["dispatch_state"] = target
    touch(unit)
    return object_response(public(unit))
