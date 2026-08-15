"""CrewAssignment endpoints: booking constraints and the hours workflow."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from flask import Blueprint

import db
from errors import (
    raise_err,
    ERR_INVALID_REQUEST,
    ERR_RESOURCE_NOT_FOUND,
    ERR_INVALID_STATE,
    ERR_NOT_RESOURCE_OWNER,
    ERR_TECHNICIAN_TURNAROUND,
    ERR_CLASSIFICATION_MISMATCH,
    ERR_HOURS_OUT_OF_RANGE,
)
from middleware import require_roles
from response import success_object
from services import calculations as calc
from services.domain import (
    check_declared,
    check_terminal,
    check_transition_owner,
    parse_to,
)
from util import get_json_body, parse_iso8601, require_string, serialize
from routes.crew_calls import get_call_or_404

bp = Blueprint("crew_assignments", __name__)

ASSIGNMENT_STATES = {"ASSIGNED", "CONFIRMED", "WORKED", "NO_SHOW", "RECONCILED", "CANCELLED"}
ASSIGNMENT_TERMINAL = {"RECONCILED", "NO_SHOW", "CANCELLED"}
ASSIGNMENT_TO_OWNERS = {
    "CONFIRMED": {"CrewChief"},
    "WORKED": {"CrewChief", "ProductionManager"},
    "NO_SHOW": {"ProductionManager"},
    # RECONCILED / CANCELLED are system-driven.
}
ASSIGNMENT_DECLARED = {
    "ASSIGNED": {"CONFIRMED", "NO_SHOW"},
    "CONFIRMED": {"WORKED", "NO_SHOW"},
    "WORKED": set(),
}

DEPARTMENT_TO_CLASSIFICATION = {
    "LIGHTING": "LIGHTING_TECH",
    "RIGGING": "RIGGER",
    "STAGEHANDS": "STAGEHAND",
}


def get_assignment_or_404(assignment_id: str) -> dict:
    asg = db.crew_assignments.get(assignment_id)
    if asg is None:
        raise_err(ERR_RESOURCE_NOT_FOUND, "CrewAssignment id does not exist")
    return asg


@bp.route("/crew-calls/<call_id>/assignments", methods=["POST"])
@require_roles("ProductionManager")
def create_assignment(call_id: str, _user_id: str, _role: str):
    body = get_json_body()
    technician_id = require_string(body, "technician_id")

    call = get_call_or_404(call_id)
    technician = db.technicians.get(technician_id)
    if technician is None:
        raise_err(ERR_RESOURCE_NOT_FOUND, "Technician id does not exist")
    if call["status"] != "PUBLISHED":
        raise_err(ERR_INVALID_STATE, "Only PUBLISHED calls accept crew")

    production = db.productions.get(call["production_id"])
    venue = db.venues.get(production["venue_id"])

    new_start = parse_iso8601(call["call_start"], "call_start")
    new_end = parse_iso8601(call["call_end"], "call_end")
    turnaround = float(venue["turnaround_min_hours"])

    # Turnaround first, then classification (PRD 3.5 pinned order).
    for other in db.crew_assignments.values():
        if other["technician_id"] != technician_id:
            continue
        if other["status"] not in ("ASSIGNED", "CONFIRMED", "WORKED"):
            continue
        other_call = db.crew_calls.get(other["crew_call_id"])
        if other_call is None:
            continue
        o_start = parse_iso8601(other_call["call_start"], "call_start")
        o_end = parse_iso8601(other_call["call_end"], "call_end")
        gap = max(
            (new_start - o_end).total_seconds() / 3600.0,
            (o_start - new_end).total_seconds() / 3600.0,
        )
        if gap < turnaround:
            raise_err(
                ERR_TECHNICIAN_TURNAROUND,
                "Rest gap between call windows is below the venue minimum",
            )

    required_classification = DEPARTMENT_TO_CLASSIFICATION[call["department"]]
    if technician["classification"] != required_classification:
        raise_err(ERR_CLASSIFICATION_MISMATCH, "Technician classification does not match department")

    assignment = {
        "crew_call_id": call_id,
        "technician_id": technician_id,
        "status": "ASSIGNED",
        "worked_hours": None,
        "labor_charge_cents": None,
    }
    db.stamp_new(assignment)
    db.crew_assignments[assignment["id"]] = assignment
    return success_object(serialize(assignment), 201)


@bp.route("/crew-assignments/<assignment_id>", methods=["GET"])
@require_roles("Any")
def get_assignment(assignment_id: str, _user_id: str, _role: str):
    return success_object(serialize(get_assignment_or_404(assignment_id)))


def _validate_worked_hours(value):
    """worked_hours must be in (0, 24] with at most 2 decimal places (fiscal
    category — runs after all state checks)."""
    dec = Decimal(str(value))
    if not (dec > 0 and dec <= 24):
        raise_err(ERR_HOURS_OUT_OF_RANGE, "worked_hours must be in (0, 24]")
    if -dec.as_tuple().exponent > 2:
        raise_err(ERR_HOURS_OUT_OF_RANGE, "worked_hours allows at most 2 decimal places")
    return value


@bp.route("/crew-assignments/<assignment_id>/transition", methods=["POST"])
@require_roles("ProductionManager", "CrewChief")
def transition_assignment(assignment_id: str, _user_id: str, _role: str):
    body = get_json_body()
    to = parse_to(body, ASSIGNMENT_STATES)
    check_transition_owner(to, ASSIGNMENT_TO_OWNERS, _role)

    assignment = get_assignment_or_404(assignment_id)

    # Ownership continuity (priority 4): a CrewChief confirms or reports hours
    # only on their own assignment.
    if _role == "CrewChief" and to in ("CONFIRMED", "WORKED"):
        if _user_id != assignment["technician_id"]:
            raise_err(ERR_NOT_RESOURCE_OWNER, "CrewChief may act only on their own assignment")

    # worked_hours presence/type is schema; the range check is fiscal (last).
    worked_hours = None
    if to == "WORKED":
        if "worked_hours" not in body or body["worked_hours"] is None:
            raise_err(ERR_INVALID_REQUEST, "Missing required field: worked_hours")
        worked_hours = body["worked_hours"]
        if isinstance(worked_hours, bool) or not isinstance(worked_hours, (int, float)):
            raise_err(ERR_INVALID_REQUEST, "Field worked_hours must be a number")

    check_terminal(assignment, ASSIGNMENT_TERMINAL, to, ASSIGNMENT_DECLARED)
    check_declared(assignment, to, ASSIGNMENT_DECLARED)

    if to == "CONFIRMED":
        assignment["status"] = "CONFIRMED"
        db.touch(assignment)
        return success_object(serialize(assignment))

    if to == "WORKED":
        assignment["worked_hours"] = _validate_worked_hours(worked_hours)
        assignment["status"] = "WORKED"
        db.touch(assignment)
        return success_object(serialize(assignment))

    # to == "NO_SHOW"
    assignment["status"] = "NO_SHOW"
    db.touch(assignment)
    return success_object(serialize(assignment))
