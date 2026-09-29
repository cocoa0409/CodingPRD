"""/client-projects - intake, technology transfer, hold release, readiness."""

from flask import Blueprint, request

import calc
import serialize
import services
from auth import acting_user, endpoint
from common import clock_str
from listing import list_response, object_response
from store import DB, by_created, engagements_of_project, new_row, set_raw, touch
from validate import (
    ANALYTICAL_STATUSES,
    DOSAGE_FORMS,
    READINESS_VARIANTS,
    TECH_STAGES,
    bad_enum,
    f_enum,
    f_int,
    f_num,
    f_str,
    parse_body,
)

bp = Blueprint("projects", __name__)

INTAKE_FIELDS = [
    f_str("client_name", 1, 120),
    f_str("molecule_name", 1, 80),
    f_enum("dosage_form", DOSAGE_FORMS),
    f_str("primary_suite_id", 1, None),
    f_num("target_fill_weight_mg", 0, exclusive_min=True),
    f_int("historical_reject_rate_ppm", 0, 100000),
    f_int("reserved_unit_budget", 0),
]


@bp.post("/client-projects")
@endpoint(["ProgramManager"])
def create_project():
    body = parse_body(request.get_json(silent=True), INTAKE_FIELDS)
    suite = services.require("suite", body["primary_suite_id"])
    row = new_row(
        {
            "client_name": body["client_name"],
            "molecule_name": body["molecule_name"],
            "dosage_form": body["dosage_form"],
            "primary_suite_id": suite["id"],
            "target_fill_weight_mg": body["target_fill_weight_mg"],
            "historical_reject_rate_ppm": body["historical_reject_rate_ppm"],
            "reserved_unit_budget": body["reserved_unit_budget"],
            "tech_transfer_stage": "NOT_STARTED",
            "analytical_method_transfer_status": "NOT_STARTED",
            "status": "INTAKE",
        }
    )
    DB.projects[row["id"]] = row
    return object_response(serialize.project_out(row), 201)


@bp.get("/client-projects/<project_id>")
@endpoint(
    [
        "ProgramManager",
        "QaReviewer",
        "QualifiedPerson",
        "MicrobiologyAnalyst",
        "ProductionSupervisor",
        "ClientRepresentative",
    ],
    crep_scope="project_path",
)
def read_project(project_id):
    row = services.require("project", project_id)
    return object_response(serialize.project_out(row))


@bp.get("/client-projects")
@endpoint(["ProgramManager", "QaReviewer", "QualifiedPerson"])
def list_projects():
    rows = by_created(list(DB.projects.values()))
    return list_response(
        rows,
        serialize.project_out,
        {"status": "status", "primary_suite_id": "primary_suite_id"},
    )


ADVANCE_FIELDS = [
    f_enum("to_stage", TECH_STAGES),
    f_enum("analytical_method_transfer_status", ANALYTICAL_STATUSES),
]


@bp.post("/client-projects/<project_id>/advance-tech-transfer")
@endpoint(["ProgramManager"])
def advance_tech_transfer(project_id):
    project = services.require("project", project_id)
    body = parse_body(request.get_json(silent=True), ADVANCE_FIELDS)
    to_stage = body["to_stage"]
    analytical = body["analytical_method_transfer_status"]
    if project["status"] != "INTAKE":
        raise services.state_conflict(
            "ERR_PROJECT_STATE_INVALID",
            "Technology transfer only advances while the project is INTAKE.",
        )
    current_index = calc.TECH_STAGE_ORDER.index(project["tech_transfer_stage"])
    if to_stage != (
        calc.TECH_STAGE_ORDER[current_index + 1]
        if current_index + 1 < len(calc.TECH_STAGE_ORDER)
        else None
    ):
        raise services.state_conflict(
            "ERR_PROJECT_STATE_INVALID",
            "to_stage must be the immediate successor of the current stage.",
        )
    stored_analytical = calc.ANALYTICAL_ORDER.index(
        project["analytical_method_transfer_status"]
    )
    if calc.ANALYTICAL_ORDER.index(analytical) < stored_analytical:
        raise services.state_conflict(
            "ERR_PROJECT_STATE_INVALID",
            "analytical_method_transfer_status may hold or advance but never regress.",
        )
    project["tech_transfer_stage"] = to_stage
    project["analytical_method_transfer_status"] = analytical
    if to_stage == "COMPLETE" and analytical == "VALIDATED":
        project["status"] = "ACTIVE"
    touch(project)
    return object_response(serialize.project_out(project))


@bp.post("/client-projects/<project_id>/release-hold")
@endpoint(["QaReviewer"])
def release_hold(project_id):
    project = services.require("project", project_id)
    parse_body(request.get_json(silent=True), [f_str("release_rationale", 1, None)])
    if project["status"] != "ON_HOLD":
        raise services.state_conflict(
            "ERR_PROJECT_STATE_INVALID", "Only an ON_HOLD project can be released."
        )
    batch_ids = set(
        b["id"] for b in DB.batches.values() if b["client_project_id"] == project["id"]
    )
    for dev in DB.deviations.values():
        if (
            dev["batch_order_id"] in batch_ids
            and dev["classification"] == "CRITICAL"
            and dev["status"] != "CLOSED"
        ):
            raise services.state_conflict(
                "ERR_OPEN_CRITICAL_DEVIATION",
                "A CRITICAL deviation of this project is still open.",
            )
    project["status"] = "ACTIVE"
    touch(project)
    services.restore_project_batches(project)
    return object_response(serialize.project_out(project))


@bp.get("/client-projects/<project_id>/readiness-assessment")
@endpoint(
    ["ProgramManager", "QaReviewer", "QualifiedPerson", "ClientRepresentative"],
    crep_scope="project_path",
)
def readiness_assessment(project_id):
    project = services.require("project", project_id)
    variant = request.args.get("variant")
    if variant is None or variant not in READINESS_VARIANTS:
        raise bad_enum("variant")
    suite = services.require("suite", project["primary_suite_id"])
    scored = calc.project_readiness_score(project, suite, variant)
    data = {
        "client_project_id": project["id"],
        "variant": variant,
        "readiness_score": scored["readiness_score"],
        "tech_points": scored["tech_points"],
        "analytical_points": scored["analytical_points"],
        "aseptic_points": scored["aseptic_points"],
        "operator_points": scored["operator_points"],
        "counted_operator_count": scored["counted_operator_count"],
        "assessed_at": clock_str(),
    }
    return object_response(data)


@bp.get("/client-projects/<project_id>/audit-engagements")
@endpoint(
    ["ProgramManager", "QaReviewer", "ClientRepresentative"],
    crep_scope="project_path",
)
def list_project_engagements(project_id):
    services.require("project", project_id)
    rows = engagements_of_project(project_id)
    return list_response(rows, serialize.engagement_out, {"status": "status"})
