"""Resurfacing projects: scoping, coordination, award, construction,
substantial completion and final acceptance (PRD 3.5, 3.7, 3.8)."""
from flask import Blueprint, g

import calc
import clock
import db
import response
import validators as v
from calc import D
from errors import ApiError
from middleware import endpoint
from services import cascades, derive

bp = Blueprint("projects", __name__)

READ_ROLES = ("PavementEngineer", "BudgetOfficer", "UtilityCoordinator",
              "Inspector", "Contractor")
ADVANCE_ACTIONS = ("START_COORDINATION", "BID_READY", "START_CONSTRUCTION")


def _find_project(project_id):
    project = db.projects.get(project_id)
    if project is None:
        raise ApiError("ERR_PROJECT_NOT_FOUND")
    return project


def _new_project_shell(scenario_id, project_name, geo_zone, start, end):
    project = {
        "id": db.new_id(),
        "scenario_id": scenario_id,
        "contractor_id": None,
        "project_name": project_name,
        "geo_zone": geo_zone,
        "planned_start_date": start,
        "planned_end_date": end,
        "delivery_status": "DRAFT",
        "quality_status": "NOT_STARTED",
        "segment_count": 0,
        "planned_area_sy": 0.0,
        "bundle_base_cents": 0,
        "contingency_cents": 0,
        "utility_share_cents": 0,
        "project_total_estimate_cents": 0,
        "award_amount_cents": None,
        "clearance_outstanding_count": 0,
        "open_remediation_count": 0,
        "accepted_at": None,
        "days_late": 0,
        "substantial_completion_at": None,
        "accepting_inspector_user_id": None,
    }
    project.update(db.audit())
    return project


@bp.post("/projects")
@endpoint("PavementEngineer")
def create_project():
    data = v.body()
    scenario_id = v.field_id(data, "scenario_id")
    project_name = v.field_string(data, "project_name", 1, 80)
    geo_zone = v.field_string(data, "geo_zone", 1, 40)
    start = v.field_datetime(data, "planned_start_date")
    end = v.field_datetime(data, "planned_end_date")
    v.window(start, end, "planned construction window")

    scenario = db.scenarios.get(scenario_id)
    if scenario is None:
        raise ApiError("ERR_SCENARIO_NOT_FOUND")
    if start < scenario["analysis_date"]:
        raise ApiError("ERR_PROJECT_WINDOW_BEFORE_ANALYSIS_DATE")
    if scenario["scenario_status"] != "ADOPTED":
        raise ApiError("ERR_SCENARIO_NOT_ADOPTED")

    project = _new_project_shell(scenario_id, project_name, geo_zone, start, end)
    db.projects[project["id"]] = project
    return response.object_response(project, 201)


@bp.get("/projects/<project_id>")
@endpoint(*READ_ROLES)
def read_project(project_id):
    project = db.projects.get(project_id)
    if project is not None and g.role == "Contractor" \
            and project["contractor_id"] != g.user_id:
        raise ApiError("ERR_NOT_PROJECT_CONTRACTOR")
    if project is None:
        raise ApiError("ERR_PROJECT_NOT_FOUND")
    return response.object_response(project)


@bp.get("/projects")
@endpoint(*READ_ROLES)
def list_projects():
    rows = v.filter_rows(db.ordered(db.projects.values()), {
        "scenario_id": "scenario_id",
        "contractor_id": "contractor_id",
        "delivery_status": "delivery_status",
        "quality_status": "quality_status",
        "geo_zone": "geo_zone",
    })
    page, meta = v.paginate(rows)
    return response.array_response(page, pagination=meta)


@bp.post("/projects/<project_id>/advance")
@endpoint("PavementEngineer")
def advance_project(project_id):
    data = v.body()
    action = v.field_enum(data, "action", ADVANCE_ACTIONS)
    project = _find_project(project_id)

    if action == "START_COORDINATION":
        if project["delivery_status"] != "DRAFT":
            raise ApiError("ERR_PROJECT_NOT_DRAFT")
        if not derive.active_lines_of_project(project["id"]):
            raise ApiError("ERR_PROJECT_HAS_NO_SEGMENTS")
        for utility in calc.UTILITIES:
            row = {
                "id": db.new_id(),
                "project_id": project["id"],
                "utility": utility,
                "coordination_status": "CLEARANCE_REQUESTED",
                "planned_work_start": None,
                "planned_work_end": None,
                "work_completed_at": None,
                "round_count": 1,
                "response_note": None,
            }
            row.update(db.audit())
            db.coordinations[row["id"]] = row
        derive.apply_updates(project, {"delivery_status": "COORDINATING"})
        derive.recompute_project_counters(project)

    elif action == "BID_READY":
        if project["delivery_status"] != "COORDINATING":
            raise ApiError("ERR_PROJECT_NOT_COORDINATING")
        if not derive.active_lines_of_project(project["id"]):
            raise ApiError("ERR_PROJECT_HAS_NO_SEGMENTS")
        outstanding = [
            c for c in derive.coordinations_of_project(project["id"])
            if c["coordination_status"] not in ("CLEARED", "CLEARED_AFTER_WORK")
        ]
        if outstanding:
            raise ApiError("ERR_UTILITY_CLEARANCE_PENDING")
        derive.recompute_project_counters(project)
        derive.apply_updates(project, {"delivery_status": "BID_READY"})
        derive.recompute_project_estimate(project)

    else:  # START_CONSTRUCTION
        if project["delivery_status"] != "AWARDED":
            raise ApiError("ERR_PROJECT_NOT_AWARDED")
        active = derive.active_lines_of_project(project["id"])
        for line in active:
            for permit in derive.permits_of_segment(line["segment_id"]):
                if permit["permit_status"] == "APPROVED" \
                        and permit["cut_completed_at"] is None:
                    raise ApiError("ERR_OPEN_CUT_ON_SEGMENT")
        for line in active:
            if line["notice_state"] != "DELIVERED":
                raise ApiError("ERR_NOTICES_NOT_DELIVERED")
        derive.apply_updates(project, {"delivery_status": "IN_CONSTRUCTION"})
        for line in active:
            if line["work_state"] == "PLANNED":
                derive.apply_updates(line, {"work_state": "IN_PROGRESS"})
        derive.recompute_project_counters(project)

    return response.object_response(project)


@bp.post("/projects/<project_id>/award")
@endpoint("BudgetOfficer")
def award_project(project_id):
    # Step 5 — segregation of duties, ahead of request shape (PRD 2.10).
    pending = db.projects.get(project_id)
    if pending is not None:
        scenario = db.scenarios.get(pending["scenario_id"])
        if scenario is not None and scenario["adopted_by_user_id"] is not None \
                and scenario["adopted_by_user_id"] == g.user_id:
            raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    data = v.body()
    contractor_id = v.field_id(data, "contractor_id")
    award_amount_cents = v.field_int(data, "award_amount_cents", minimum=0)

    project = _find_project(project_id)
    contractor = db.contractors.get(contractor_id)
    if contractor is None:
        raise ApiError("ERR_CONTRACTOR_NOT_FOUND")

    if project["delivery_status"] != "BID_READY":
        raise ApiError("ERR_PROJECT_NOT_BID_READY")
    scenario = db.scenarios.get(project["scenario_id"])
    if scenario is None or scenario["scenario_status"] != "ADOPTED":
        raise ApiError("ERR_SCENARIO_NOT_ADOPTED")
    if contractor["standing"] != "GOOD_STANDING":
        raise ApiError("ERR_CONTRACTOR_NOT_IN_GOOD_STANDING")

    overlapping = 0
    for other in derive.projects_of_contractor(contractor["id"]):
        if other["id"] == project["id"]:
            continue
        if other["delivery_status"] not in ("AWARDED", "IN_CONSTRUCTION"):
            continue
        if other["planned_start_date"] <= project["planned_end_date"] \
                and other["planned_end_date"] >= project["planned_start_date"]:
            overlapping += 1
    if overlapping + 1 > contractor["max_concurrent_projects"]:
        raise ApiError("ERR_CONTRACTOR_CAPACITY_EXCEEDED")

    if award_amount_cents > scenario["uncommitted_cents"]:
        raise ApiError("ERR_SCENARIO_FUNDS_EXCEEDED")
    estimate = D(project["project_total_estimate_cents"])
    if abs(D(award_amount_cents) - estimate) > estimate * calc.AWARD_TOLERANCE_PCT:
        raise ApiError("ERR_AWARD_OUTSIDE_ESTIMATE_TOLERANCE")

    derive.apply_updates(project, {
        "delivery_status": "AWARDED",
        "contractor_id": contractor["id"],
        "award_amount_cents": award_amount_cents,
    })
    derive.recompute_scenario_totals(scenario)
    return response.object_response(project)


@bp.post("/projects/<project_id>/cancel-award")
@endpoint("BudgetOfficer")
def cancel_award(project_id):
    data = v.body()
    v.field_string(data, "cancellation_reason", 1, 500, required=False)
    project = _find_project(project_id)
    if project["delivery_status"] != "AWARDED":
        raise ApiError("ERR_PROJECT_NOT_AWARDED")
    derive.apply_updates(project, {
        "delivery_status": "BID_READY",
        "contractor_id": None,
        "award_amount_cents": None,
    })
    scenario = db.scenarios.get(project["scenario_id"])
    if scenario is not None:
        derive.recompute_scenario_totals(scenario)
    return response.object_response(project)


@bp.post("/projects/<project_id>/substantial-completion")
@endpoint("Contractor")
def substantial_completion(project_id):
    # Step 4 — caller ownership, ahead of request shape (PRD 2.10).
    pending = db.projects.get(project_id)
    if pending is not None and pending["contractor_id"] != g.user_id:
        raise ApiError("ERR_NOT_PROJECT_CONTRACTOR")

    v.body()
    project = _find_project(project_id)
    if project["delivery_status"] != "IN_CONSTRUCTION":
        raise ApiError("ERR_PROJECT_NOT_IN_CONSTRUCTION")
    for line in derive.lines_of_project(project["id"]):
        if line["work_state"] in ("PLANNED", "IN_PROGRESS"):
            raise ApiError("ERR_LINES_WORK_INCOMPLETE")

    now = clock.now()
    if now < project["planned_start_date"]:
        raise ApiError("ERR_COMPLETION_BEFORE_START")

    days_late = max(0, calc.whole_days(project["planned_end_date"], now))
    derive.apply_updates(project, {
        "delivery_status": "SUBSTANTIALLY_COMPLETE",
        "substantial_completion_at": now,
        "days_late": days_late,
    })
    contractor = db.contractors.get(project["contractor_id"])
    if contractor is not None:
        derive.recompute_contractor_scores(contractor)
    return response.object_response(project)


@bp.post("/projects/<project_id>/accept")
@endpoint("Inspector")
def accept_project(project_id):
    # Step 5 — segregation of duties, ahead of request shape (PRD 2.10).
    pending = db.projects.get(project_id)
    if pending is not None:
        for test in derive.tests_of_project(pending["id"]):
            if test["witness_inspector_user_id"] == g.user_id:
                raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    data = v.body()
    v.field_string(data, "acceptance_note", 1, 500, required=False)
    project = _find_project(project_id)

    if project["delivery_status"] != "SUBSTANTIALLY_COMPLETE":
        raise ApiError("ERR_PROJECT_NOT_SUBSTANTIALLY_COMPLETE")
    if project["quality_status"] != "QUALITY_ACCEPTED":
        raise ApiError("ERR_REMEDIATION_OUTSTANDING")

    for line in derive.active_lines_of_project(project["id"]):
        if line["treatment_type"] == "CRACK_SEAL":
            continue
        tests = derive.tests_of_line(line["id"])
        if not tests:
            raise ApiError("ERR_ACCEPTANCE_TESTS_INCOMPLETE")
        top_round = max(t["test_round"] for t in tests)
        if not any(t["test_round"] == top_round and t["test_status"] == "PASSED"
                   for t in tests):
            raise ApiError("ERR_ACCEPTANCE_TESTS_INCOMPLETE")

    cascades.accept_project(project, g.user_id)
    return response.object_response(project)
