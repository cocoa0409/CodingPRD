"""Tank project intake, reads and the tank-locating sweep survey."""

from flask import Blueprint

import calculations as calc
from db import assign, create, db
from errors import ApiError
from middleware import (ALL_ROLES, authenticate, body, filter_arg, opt_id, opt_num,
                        pagination, req_bool, req_enum, req_int, require_project_owner,
                        resolve)
from response import entity_response, list_response, object_response
from services import project as svc

bp = Blueprint("projects", __name__)

READ_ROLES = ("ProjectCoordinator", "FieldTechnician", "LabAnalyst",
              "LicensedSiteProfessional", "ComplianceOfficer")
SUMMARY_ROLES = ("ProjectCoordinator", "LicensedSiteProfessional", "ComplianceOfficer")


@bp.post("/tank-projects")
def create_project():
    authenticate(("ProjectCoordinator",))
    payload = body()
    property_id = opt_id(payload, "property_id")
    prop = resolve("properties", property_id) if property_id else None
    if prop is None:
        raise ApiError("ERR_INVALID_REQUEST", "property_id is required.")
    baseline = opt_num(payload, "baseline_scope_cubic_yards", calc.dec("8.0"), exclusive_min=0)
    limit = opt_num(payload, "excavation_limit_cubic_yards", calc.dec("40.0"), exclusive_min=0)

    project = create("tank_projects", {
        "property_id": prop["id"],
        "status": "INTAKE",
        "survey_method": None,
        "survey_completed_at": None,
        "tanks_detected_count": None,
        "tank_capacity_gallons": None,
        "tank_depth_to_top_inches": None,
        "tank_distance_to_foundation_inches": None,
        "tank_under_structure": None,
        "tank_material": None,
        "method_score": None,
        "recommended_method": None,
        "decommission_method": None,
        "baseline_scope_cubic_yards": baseline,
        "excavation_limit_cubic_yards": limit,
        "approved_scope_cubic_yards": baseline,
        "sampling_round": 0,
        "contamination_class": "UNCLASSIFIED",
        "max_tph_mg_kg": None,
        "max_benzene_mg_kg": None,
        "remediation_started": False,
        "contamination_disclosure_required": False,
        "remediation_volume_cubic_yards": None,
        "remediation_volume_basis": None,
        "remediation_cost_cents": 0,
        "actual_excavated_cubic_yards": None,
        "hauled_tons": None,
        "nfa_blockers": [],
    })
    project["nfa_blockers"] = svc.compute_blockers(project)
    svc.increment_open_projects(prop)
    return entity_response(project, 201)


@bp.get("/tank-projects")
def list_projects():
    authenticate(READ_ROLES)
    limit, offset = pagination()
    property_id = filter_arg("property_id")
    status = filter_arg("status")
    rows = list(db.tank_projects.values())
    if property_id is not None:
        rows = [r for r in rows if r["property_id"] == property_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return list_response(rows, limit, offset)


@bp.get("/tank-projects/<project_id>")
def read_project(project_id):
    user_id, role = authenticate(ALL_ROLES)
    project = resolve("tank_projects", project_id)
    require_project_owner(project, user_id, role)
    return entity_response(project)


@bp.get("/tank-projects/<project_id>/summary")
def read_summary(project_id):
    authenticate(SUMMARY_ROLES)
    project = resolve("tank_projects", project_id)
    return object_response(svc.summary(project))


@bp.post("/tank-projects/<project_id>/sweep-survey")
def sweep_survey(project_id):
    authenticate(("ProjectCoordinator", "FieldTechnician"))
    project = resolve("tank_projects", project_id)
    payload = body()

    survey_method = req_enum(payload, "survey_method", calc.SURVEY_METHODS)
    tanks_detected_count = req_int(payload, "tanks_detected_count", minimum=0)
    descriptors = {}
    if tanks_detected_count >= 1:
        # The five descriptors are required only when a tank was located.
        descriptors = {
            "tank_capacity_gallons": req_int(payload, "tank_capacity_gallons", minimum=0),
            "tank_depth_to_top_inches": req_int(
                payload, "tank_depth_to_top_inches", minimum=0),
            "tank_distance_to_foundation_inches": req_int(
                payload, "tank_distance_to_foundation_inches", minimum=0),
            "tank_under_structure": req_bool(payload, "tank_under_structure"),
            "tank_material": req_enum(payload, "tank_material", calc.TANK_MATERIALS),
        }

    if project["status"] != "INTAKE":
        raise ApiError("ERR_PROJECT_STATE_INVALID")
    if tanks_detected_count == 0:
        raise ApiError("ERR_NO_TANK_LOCATED")

    assign(project, "survey_method", survey_method)
    assign(project, "tanks_detected_count", tanks_detected_count)
    assign(project, "survey_completed_at", db.now())
    for field, value in descriptors.items():
        assign(project, field, value)

    score, method = calc.method_recommendation(
        descriptors["tank_capacity_gallons"],
        descriptors["tank_depth_to_top_inches"],
        descriptors["tank_distance_to_foundation_inches"],
        descriptors["tank_under_structure"],
        descriptors["tank_material"],
    )
    assign(project, "method_score", score)
    assign(project, "recommended_method", method)
    assign(project, "status", "SURVEYED")
    svc.recompute_blockers(project)
    svc.bump_project_version(project)
    return entity_response(project)
