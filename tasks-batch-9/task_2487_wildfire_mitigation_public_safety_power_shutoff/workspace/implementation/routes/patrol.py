"""Patrol assignment and damage finding endpoints."""

from decimal import Decimal

from flask import Blueprint

import clock
import db
import validation as v
from errors import ApiError
from middleware import (
    ASSET_INSPECTOR,
    FIELD_PATROL_SUPERVISOR,
    GRID_PLANNER,
    PSPS_DUTY_OFFICER,
    REGULATORY_REVIEWER,
    TRANSMISSION_ENGINEER,
    roles,
)
from response import object_response
from services import calc

bp = Blueprint("patrol", __name__)

PATROL_MODES = ("GROUND", "AERIAL", "DRONE")
PATROL_STATUSES = ("SCHEDULED", "IN_PROGRESS", "COMPLETED", "ABORTED")
SEVERITIES = ("MINOR", "MAJOR", "IGNITION_RISK")
PATROL_PHASES = ("DE_ENERGIZED", "PATROL_IN_PROGRESS", "CLEARED_FOR_RESTORE")

READ_ROLES = (
    GRID_PLANNER,
    PSPS_DUTY_OFFICER,
    REGULATORY_REVIEWER,
    FIELD_PATROL_SUPERVISOR,
    TRANSMISSION_ENGINEER,
)
FINDING_READ_ROLES = (
    GRID_PLANNER,
    PSPS_DUTY_OFFICER,
    REGULATORY_REVIEWER,
    FIELD_PATROL_SUPERVISOR,
    ASSET_INSPECTOR,
    TRANSMISSION_ENGINEER,
)


def _assert_patrol_phase(circuit):
    if circuit["energization_state"] not in PATROL_PHASES:
        raise ApiError(
            "ERR_CIRCUIT_NOT_DE_ENERGIZED",
            "Circuit %s is %s, not in a post-shutoff patrol phase."
            % (circuit["circuit_code"], circuit["energization_state"]),
        )


@bp.post("/patrol-assignments")
@roles(FIELD_PATROL_SUPERVISOR)
def create_assignment():
    body = v.Body()
    event_id = body.string("psps_event_id", 1, None)
    circuit_id = body.string("circuit_id", 1, None)
    patrol_mode = body.enum("patrol_mode", PATROL_MODES)
    window_start, window_start_raw = body.timestamp("window_start_at")
    window_end, window_end_raw = body.timestamp("window_end_at")
    patrol_lead = body.string("patrol_lead_user_id", 1, 64)

    event = v.psps_event(event_id)
    circuit = v.circuit(circuit_id)

    # Priority 9 - the circuit must be in a post-shutoff phase.
    _assert_patrol_phase(circuit)

    # Priority 13 - the window must be well formed.
    if window_end <= window_start:
        raise ApiError(
            "ERR_PATROL_WINDOW_INVALID",
            "window_end_at must be strictly later than window_start_at.",
        )

    # Priority 16 - closed windows on one circuit may not intersect.
    for other in db.patrol_assignments.values():
        if other["circuit_id"] != circuit["id"]:
            continue
        if other["status"] not in ("SCHEDULED", "IN_PROGRESS"):
            continue
        if window_start <= other["window_end_at"] and other["window_start_at"] <= window_end:
            raise ApiError(
                "ERR_PATROL_WINDOW_OVERLAP",
                "The window intersects another live patrol window on this circuit.",
            )

    row = db.new_row()
    row["psps_event_id"] = event["id"]
    row["circuit_id"] = circuit["id"]
    row["patrol_mode"] = patrol_mode
    db.set_dt(row, "window_start_at", window_start, window_start_raw)
    db.set_dt(row, "window_end_at", window_end, window_end_raw)
    row["patrol_lead_user_id"] = patrol_lead
    row["status"] = "SCHEDULED"
    db.set_dt(row, "started_at", None)
    db.set_dt(row, "completed_at", None)
    row["miles_patrolled"] = Decimal("0.0")
    row["damage_finding_count"] = 0
    row["ignition_risk_finding_count"] = 0
    db.patrol_assignments[row["id"]] = row
    return object_response(db.patrol_assignment_out(row), 201)


@bp.get("/patrol-assignments")
@roles(*READ_ROLES)
def list_assignments():
    event_id = v.query_string("psps_event_id")
    circuit_id = v.query_string("circuit_id")
    status = v.query_enum("status", PATROL_STATUSES)

    rows = db.in_order(db.patrol_assignments.values())
    if event_id is not None:
        rows = [r for r in rows if r["psps_event_id"] == event_id]
    if circuit_id is not None:
        rows = [r for r in rows if r["circuit_id"] == circuit_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return v.paged(rows, db.patrol_assignment_out)


@bp.get("/patrol-assignments/<assignment_id>")
@roles(*READ_ROLES)
def get_assignment(assignment_id):
    return object_response(db.patrol_assignment_out(v.patrol_assignment(assignment_id)))


@bp.post("/patrol-assignments/<assignment_id>/start")
@roles(FIELD_PATROL_SUPERVISOR)
def start_assignment(assignment_id):
    assignment = v.patrol_assignment(assignment_id)

    # Priority 8 - the assignment's own state.
    if assignment["status"] != "SCHEDULED":
        raise ApiError(
            "ERR_PATROL_INVALID_STATE",
            "A %s patrol cannot be started." % assignment["status"],
        )

    event = db.psps_events.get(assignment["psps_event_id"])
    circuit = db.circuits.get(assignment["circuit_id"])

    # Priority 9 - the governing event, then the circuit.
    if event is None or event["scope_status"] != "RESTORING":
        raise ApiError(
            "ERR_EVENT_NOT_IN_RESTORATION",
            "The governing shutoff event is not in restoration.",
        )
    _assert_patrol_phase(circuit)

    assignment["status"] = "IN_PROGRESS"
    db.set_dt(assignment, "started_at", clock.now())
    db.touch(assignment)

    if circuit["energization_state"] in ("DE_ENERGIZED", "CLEARED_FOR_RESTORE"):
        circuit["energization_state"] = "PATROL_IN_PROGRESS"
    calc.recompute_risk_posture(circuit)
    db.touch(circuit)

    return object_response(db.patrol_assignment_out(assignment))


@bp.post("/patrol-assignments/<assignment_id>/complete")
@roles(FIELD_PATROL_SUPERVISOR)
def complete_assignment(assignment_id):
    assignment = v.patrol_assignment(assignment_id)
    body = v.Body()
    miles = body.number("miles_patrolled", minimum=0)

    # Priority 8 - the assignment's own state.
    if assignment["status"] != "IN_PROGRESS":
        raise ApiError(
            "ERR_PATROL_INVALID_STATE",
            "A %s patrol cannot be completed." % assignment["status"],
        )

    assignment["status"] = "COMPLETED"
    db.set_dt(assignment, "completed_at", clock.now())
    assignment["miles_patrolled"] = miles
    db.touch(assignment)

    circuit = db.circuits.get(assignment["circuit_id"])
    if circuit is not None:
        # Completion clears the circuit for restoration unconditionally.
        if circuit["energization_state"] == "PATROL_IN_PROGRESS":
            circuit["energization_state"] = "CLEARED_FOR_RESTORE"
        calc.recompute_risk_posture(circuit)
        db.touch(circuit)

    return object_response(db.patrol_assignment_out(assignment))


@bp.post("/damage-findings")
@roles(FIELD_PATROL_SUPERVISOR)
def create_finding():
    body = v.Body()
    assignment_id = body.string("patrol_assignment_id", 1, None)
    severity = body.enum("severity", SEVERITIES)
    description = body.string("description", 1, 500)
    requires_repair = body.boolean("requires_repair", required=True)

    assignment = v.patrol_assignment(assignment_id)

    # Priority 8 - findings are filed only against an in-progress patrol.
    if assignment["status"] != "IN_PROGRESS":
        raise ApiError(
            "ERR_PATROL_INVALID_STATE",
            "Findings are filed only against an IN_PROGRESS patrol.",
        )

    row = db.new_row(versioned=False)
    row["patrol_assignment_id"] = assignment["id"]
    row["severity"] = severity
    row["description"] = description
    row["requires_repair"] = requires_repair
    db.set_dt(row, "found_at", clock.now())
    db.damage_findings[row["id"]] = row

    assignment["damage_finding_count"] = int(assignment["damage_finding_count"]) + 1
    if severity == "IGNITION_RISK":
        assignment["ignition_risk_finding_count"] = (
            int(assignment["ignition_risk_finding_count"]) + 1
        )
    db.touch(assignment)

    return object_response(db.damage_finding_out(row), 201)


@bp.get("/patrol-assignments/<assignment_id>/damage-findings")
@roles(*FINDING_READ_ROLES)
def list_findings(assignment_id):
    assignment = v.patrol_assignment(assignment_id)
    severity = v.query_enum("severity", SEVERITIES)
    rows = [
        f
        for f in db.in_order(db.damage_findings.values())
        if f["patrol_assignment_id"] == assignment["id"]
    ]
    if severity is not None:
        rows = [r for r in rows if r["severity"] == severity]
    return v.paged(rows, db.damage_finding_out)
