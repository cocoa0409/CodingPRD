"""Mitigation project endpoints: booking, the revision loop and execution."""

from decimal import Decimal

from flask import Blueprint, g

import db
import validation as v
from errors import ApiError
from middleware import (
    ASSET_INSPECTOR,
    GRID_PLANNER,
    PSPS_DUTY_OFFICER,
    REGULATORY_REVIEWER,
    TRANSMISSION_ENGINEER,
    roles,
)
from response import object_response
from services import calc

bp = Blueprint("mitigation", __name__)

PROGRAM_TYPES = (
    "COVERED_CONDUCTOR",
    "UNDERGROUNDING",
    "FAST_TRIP_SETTING",
    "INSPECTION_CYCLE",
)
DECISIONS = ("APPROVE", "REQUEST_REVISION", "WITHDRAW")

READ_ROLES = (
    GRID_PLANNER,
    PSPS_DUTY_OFFICER,
    REGULATORY_REVIEWER,
    ASSET_INSPECTOR,
    TRANSMISSION_ENGINEER,
)


def _assert_not_locked(circuit):
    if circuit["risk_posture"] == "LOCKED":
        raise ApiError(
            "ERR_CIRCUIT_POSTURE_LOCKED",
            "Circuit %s is LOCKED for hardening work." % circuit["circuit_code"],
        )


@bp.post("/mitigation-projects")
@roles(GRID_PLANNER)
def create_project():
    body = v.Body()
    project_code = body.string("project_code", 3, 40)
    circuit_id = body.string("circuit_id", 1, None)
    program_type = body.enum("program_type", PROGRAM_TYPES)
    plan_year = body.integer("plan_year", minimum=2020, maximum=2100)
    planned_miles = body.number("planned_miles", exclusive_minimum=0, max_decimals=1)
    unit_cost = body.integer("unit_cost_per_mile_cents", minimum=0)

    circuit = v.circuit(circuit_id)

    # Priority 9 - the governing circuit must not be LOCKED.
    _assert_not_locked(circuit)

    # Priority 15 - the natural key.
    v.unique_code(db.mitigation_projects, "project_code", project_code)

    row = db.new_row()
    row["project_code"] = project_code
    row["circuit_id"] = circuit["id"]
    row["program_type"] = program_type
    row["plan_year"] = plan_year
    row["planned_miles"] = planned_miles
    row["unit_cost_per_mile_cents"] = unit_cost
    row["budget_cents"] = calc.budget_cents(planned_miles, unit_cost)
    row["completed_miles"] = Decimal("0.0")
    row["risk_reduction_score"] = calc.risk_reduction_score(
        planned_miles, program_type, circuit["hftd_tier"]
    )
    row["status"] = "DRAFT"
    row["review_round"] = 0
    row["last_revision_reviewer_user_id"] = None
    row["last_review_note"] = None
    db.mitigation_projects[row["id"]] = row
    return object_response(db.mitigation_project_out(row), 201)


@bp.get("/mitigation-projects/<project_id>")
@roles(*READ_ROLES)
def get_project(project_id):
    return object_response(db.mitigation_project_out(v.mitigation_project(project_id)))


@bp.post("/mitigation-projects/<project_id>/submit")
@roles(GRID_PLANNER)
def submit_project(project_id):
    project = v.mitigation_project(project_id)

    # Priority 8 - the project's own state.
    if project["status"] not in ("DRAFT", "REVISION_REQUESTED"):
        raise ApiError(
            "ERR_PROJECT_INVALID_STATE",
            "A %s project cannot be submitted." % project["status"],
        )

    circuit = db.circuits.get(project["circuit_id"])

    # Priority 9 - the governing circuit must not have become LOCKED.
    _assert_not_locked(circuit)

    project["status"] = "SUBMITTED"
    project["risk_reduction_score"] = calc.risk_reduction_score(
        project["planned_miles"], project["program_type"], circuit["hftd_tier"]
    )
    db.touch(project)
    return object_response(db.mitigation_project_out(project))


@bp.post("/mitigation-projects/<project_id>/review")
@roles(REGULATORY_REVIEWER)
def review_project(project_id):
    project = v.mitigation_project(project_id)
    body = v.Body()
    decision = body.enum("decision", DECISIONS)
    review_note = body.string("review_note", required=False, default=None)

    # Priority 8 - the project's own state.
    if decision == "WITHDRAW":
        admitted = project["status"] in ("IN_EXECUTION", "SUSPENDED", "COMPLETED")
    else:
        admitted = project["status"] == "SUBMITTED"
    if not admitted:
        raise ApiError(
            "ERR_PROJECT_INVALID_STATE",
            "Decision %s is not admitted while the project is %s."
            % (decision, project["status"]),
        )

    # Priority 12 - the project-approval segregation-of-duties gate.
    if decision == "APPROVE":
        reviewer = project["last_revision_reviewer_user_id"]
        if reviewer is not None and reviewer == g.user_id:
            raise ApiError(
                "ERR_SEGREGATION_OF_DUTIES",
                "The reviewer who demanded the revision may not approve it.",
            )

    # Priority 17 - the revision ceiling.
    if decision == "REQUEST_REVISION" and int(project["review_round"]) >= 2:
        raise ApiError(
            "ERR_REVIEW_ROUND_LIMIT",
            "The project has already absorbed two revision requests.",
        )

    if decision == "APPROVE":
        project["status"] = "APPROVED"
        project["last_review_note"] = review_note
        db.touch(project)
    elif decision == "REQUEST_REVISION":
        project["status"] = "REVISION_REQUESTED"
        project["review_round"] = int(project["review_round"]) + 1
        project["last_revision_reviewer_user_id"] = g.user_id
        project["last_review_note"] = review_note
        db.touch(project)
    else:
        circuit = db.circuits.get(project["circuit_id"])
        project["status"] = "WITHDRAWN"
        project["completed_miles"] = Decimal("0.0")
        db.touch(project)
        calc.recompute_hardened_mileage(circuit)
        calc.recompute_risk_posture(circuit)
        db.touch(circuit)

    return object_response(db.mitigation_project_out(project))


@bp.post("/mitigation-projects/<project_id>/record-completion")
@roles(ASSET_INSPECTOR)
def record_completion(project_id):
    project = v.mitigation_project(project_id)
    body = v.Body()
    delta = body.number("completed_miles_delta", exclusive_minimum=0)
    completion_text = body.string("completion_date", 1, None)
    expected = body.integer("expected_circuit_version")

    if v.DATE_RE.match(completion_text):
        completion_at = v.parse_datetime(completion_text + "T00:00:00Z", "completion_date")
        completion_raw = None
    else:
        completion_at = v.parse_datetime(completion_text, "completion_date")
        completion_raw = completion_text

    circuit = db.circuits.get(project["circuit_id"])

    # Priority 7 - the parent version guard.
    if expected != circuit["version"]:
        raise ApiError(
            "ERR_STALE_VERSION",
            "expected_circuit_version %s does not match the stored version %s."
            % (expected, circuit["version"]),
        )

    # Priority 8 - the project's own state.
    if project["status"] not in ("APPROVED", "IN_EXECUTION"):
        raise ApiError(
            "ERR_PROJECT_INVALID_STATE",
            "Completion cannot be recorded while the project is %s." % project["status"],
        )

    # Priority 17 - the planned-mileage ceiling.
    total = calc.D(project["completed_miles"]) + calc.D(delta)
    planned = calc.D(project["planned_miles"])
    if total > planned:
        raise ApiError(
            "ERR_MITIGATION_MILES_EXCEEDED",
            "Cumulative completed mileage %s would exceed the planned %s."
            % (total, planned),
        )

    project["completed_miles"] = total
    project["status"] = "COMPLETED" if total == planned else "IN_EXECUTION"

    if project["program_type"] == "INSPECTION_CYCLE":
        db.set_dt(circuit, "last_inspection_completed_at", completion_at, completion_raw)
    elif project["program_type"] == "FAST_TRIP_SETTING":
        if project["status"] == "COMPLETED":
            circuit["fast_trip_enabled"] = True

    db.touch(project)
    calc.recompute_hardened_mileage(circuit)
    calc.recompute_risk_posture(circuit)
    db.touch(circuit)

    return object_response(db.mitigation_project_out(project))
