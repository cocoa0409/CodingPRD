"""ExhibitProject endpoints (PRD §3.1, §3.9 closeout, §3.3 sweep)."""

from flask import Blueprint

import calc
import cascades
import helpers
import serializers
from auth import ALL_ROLES, ROLE_PROJECT_MANAGER, caller_id, endpoint
from envelope import list_response, object_response, pagination, query_filter
from errors import ApiError
from helpers import PHASE_LADDER, PHASE_SUCCESSOR, touch
from store import db, new_row, order_created
from validate import body_object, v_datetime, v_enum, v_int, v_objective_codes, v_str

bp = Blueprint("projects", __name__)


@bp.route("/exhibit-projects", methods=["POST"])
@endpoint(roles=[ROLE_PROJECT_MANAGER])
def create_project():
    body = body_object()
    name = v_str(body, "name", 1, 160, non_blank=True)
    museum_name = v_str(body, "museum_name", 1, 160, non_blank=True)
    storyline_title = v_str(body, "storyline_title", 1, 200, non_blank=True)
    objective_codes = v_objective_codes(body, "objective_codes")
    target_open_date = v_datetime(body, "target_open_date")
    contract_value_cents = v_int(body, "contract_value_cents", minimum=1000000)
    max_concurrent_closures = v_int(body, "max_concurrent_closures", minimum=1, maximum=5,
                                   required=False, default=calc.DEFAULT_MAX_CONCURRENT_CLOSURES)
    project = new_row("projects", {
        "name": name,
        "museum_name": museum_name,
        "storyline_title": storyline_title,
        "objective_codes": objective_codes,
        "target_open_date": target_open_date,
        "contract_value_cents": contract_value_cents,
        "max_concurrent_closures": max_concurrent_closures,
        "phase": "INTERPRETIVE",
        "conservation_veto_count": 0,
        "committed_fabrication_cents": 0,
        "retainage_held_cents": 0,
        "warranty_reserve_cents": 0,
        "released_cents": 0,
        "parts_commitment_years": 0,
        "docent_kit_url": None,
        "maintenance_manual_url": None,
        "warranty_registered_at": None,
        "created_by_user_id": caller_id(),
    })
    db.projects[project["id"]] = project
    return object_response(serializers.project_json(project), 201)


@bp.route("/exhibit-projects", methods=["GET"])
@endpoint(roles=ALL_ROLES)
def list_projects():
    limit, offset = pagination()
    phase = query_filter("phase")
    posture = query_filter("posture")
    rows = list(db.projects.values())
    if phase is not None:
        rows = [r for r in rows if r["phase"] == phase]
    if posture is not None:
        rows = [r for r in rows if helpers.project_posture(r) == posture]
    # The top-level project list is ordered by created_at DESCENDING (PRD §2.3).
    rows.sort(key=order_created, reverse=True)
    return list_response(rows, serializers.project_json, limit, offset)


@bp.route("/exhibit-projects/<pid>", methods=["GET"])
@endpoint(roles=ALL_ROLES)
def get_project(pid):
    project = helpers.get_project(pid)
    return object_response(serializers.project_json(project))


@bp.route("/exhibit-projects/<pid>/advance-phase", methods=["POST"])
@endpoint(roles=[ROLE_PROJECT_MANAGER])
def advance_phase(pid):
    project = helpers.get_project(pid)
    body = body_object()
    to_phase = v_enum(body, "to_phase", PHASE_LADDER)

    # Step 10: the destination must be the immediate successor.
    successor = PHASE_SUCCESSOR.get(project["phase"], None)
    if successor is None or to_phase != successor:
        raise ApiError("ERR_INVALID_PROJECT_PHASE",
                       "%s is not the immediate successor of %s." % (to_phase, project["phase"]))

    # Step 11: posture.  Advancing to INSTALLATION is one of the two OPEN-only gates.
    if to_phase == "INSTALLATION":
        helpers.require_posture_open(project)
    else:
        helpers.require_not_frozen(project)

    # Step 12/13: the admission test for this particular step.
    if to_phase == "SCHEMATIC":
        if project["storyline_title"].strip() == "" or len(project["objective_codes"]) < 2:
            raise ApiError("ERR_INVALID_PROJECT_PHASE",
                           "Interpretive planning is not signed off.")
    elif to_phase == "DESIGN_DEV":
        if not _has_approved_package(project, "SCHEMATIC"):
            raise ApiError("ERR_INVALID_PROJECT_PHASE",
                           "No APPROVED SCHEMATIC design package on file.")
    elif to_phase == "FABRICATION":
        if not _has_approved_package(project, "DESIGN_DEV"):
            raise ApiError("ERR_INVALID_PROJECT_PHASE",
                           "No APPROVED DESIGN_DEV design package on file.")
        carried = set()
        for case in helpers.rows_of_project(db.cases, project["id"]):
            if case["objective_code"] is not None:
                carried.add(case["objective_code"])
        for interactive in helpers.rows_of_project(db.interactives, project["id"]):
            if interactive["objective_code"] is not None:
                carried.add(interactive["objective_code"])
        for code in project["objective_codes"]:
            if code not in carried:
                raise ApiError("ERR_OBJECTIVE_NOT_ADDRESSED",
                               "Objective %s is carried by nothing buildable." % code)
    elif to_phase == "INSTALLATION":
        cases = helpers.rows_of_project(db.cases, project["id"])
        if len(cases) < 1 or any(c["status"] != "APPROVED" for c in cases):
            raise ApiError("ERR_INVALID_PROJECT_PHASE",
                           "Every artifact case must be APPROVED and at least one must exist.")
        drawings = helpers.rows_of_project(db.drawings, project["id"])
        if not any(d["status"] in ("APPROVED", "APPROVED_AS_NOTED") for d in drawings):
            raise ApiError("ERR_INVALID_PROJECT_PHASE",
                           "No approved shop drawing on file.")
    elif to_phase == "COMMISSIONING":
        windows = helpers.rows_of_project(db.windows, project["id"])
        if any(w["status"] not in ("COMPLETED", "DENIED", "CANCELLED") for w in windows):
            raise ApiError("ERR_INVALID_PROJECT_PHASE", "An install window is still live.")
        for artifact in helpers.rows_of_project(db.artifacts, project["id"]):
            if artifact["assigned_case_id"] is not None and artifact["placement_status"] != "PLACED":
                raise ApiError("ERR_INVALID_PROJECT_PHASE",
                               "A collection object assigned to a case is not PLACED.")
    elif to_phase == "CLOSEOUT":
        counters = helpers.project_counters(project)
        if counters["blocking_punch_count"] != 0:
            raise ApiError("ERR_BLOCKING_PUNCH_ITEMS_OPEN")
        for interactive in helpers.rows_of_project(db.interactives, project["id"]):
            if interactive["status"] != "COMMISSIONED":
                raise ApiError("ERR_INVALID_PROJECT_PHASE",
                               "Every interactive must be COMMISSIONED.")

    project["phase"] = to_phase
    touch(project)
    return object_response(serializers.project_json(project))


def _has_approved_package(project, stage):
    for package in helpers.packages_of_project(project["id"]):
        if package["stage"] == stage and package["status"] == "APPROVED":
            return True
    return False


@bp.route("/exhibit-projects/<pid>/review-sweep", methods=["POST"])
@endpoint(roles=[ROLE_PROJECT_MANAGER])
def review_sweep(pid):
    project = helpers.get_project(pid)
    cascades.review_sweep(project)
    return object_response(serializers.project_json(project))


@bp.route("/exhibit-projects/<pid>/closeout", methods=["POST"])
@endpoint(roles=[ROLE_PROJECT_MANAGER])
def closeout(pid):
    project = helpers.get_project(pid)
    body = body_object()
    docent_kit_url = v_str(body, "docent_kit_url", 1, 500, non_blank=True)
    maintenance_manual_url = v_str(body, "maintenance_manual_url", 1, 500, non_blank=True)
    parts_commitment_years = v_int(body, "parts_commitment_years", minimum=0)

    helpers.require_phase(project, ("CLOSEOUT",))
    helpers.require_posture_open(project)
    if project["committed_fabrication_cents"] <= 0:
        raise ApiError("ERR_NOTHING_TO_SETTLE")

    # Step one: integer addition over the project's money-committing sheets.
    fabrication_total = 0
    for drawing in helpers.rows_of_project(db.drawings, project["id"]):
        if drawing["status"] in ("APPROVED", "APPROVED_AS_NOTED") and drawing["actual_cost_cents"]:
            fabrication_total += drawing["actual_cost_cents"]
    commissioned_parts_years = [i["parts_availability_years"]
                                for i in helpers.rows_of_project(db.interactives, project["id"])
                                if i["status"] == "COMMISSIONED"]
    settlement = calc.closeout_settlement(fabrication_total, commissioned_parts_years)

    project["retainage_held_cents"] = settlement["retainage_held_cents"]
    project["warranty_reserve_cents"] = settlement["warranty_reserve_cents"]
    project["released_cents"] = settlement["released_cents"]
    project["committed_fabrication_cents"] = 0
    project["docent_kit_url"] = docent_kit_url
    project["maintenance_manual_url"] = maintenance_manual_url
    project["parts_commitment_years"] = parts_commitment_years
    project["warranty_registered_at"] = db.now()

    for item in helpers.rows_of_project(db.punch_items, project["id"]):
        if item["status"] in ("VERIFIED", "WAIVED"):
            item["status"] = "CLOSED"
            touch(item)

    project["phase"] = "WARRANTY_CLOSED"
    touch(project)
    return object_response(serializers.project_json(project))
