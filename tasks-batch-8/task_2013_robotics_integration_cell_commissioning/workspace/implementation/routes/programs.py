"""RobotProgram endpoints — parallel dev/sim state axes (PRD §3.5)."""
from flask import Blueprint, request

from db import children, store
from errors import (ApiError, ERR_DUPLICATE_CODE, ERR_SEGREGATION_OF_DUTIES,
                    invalid_state, not_found)
from middleware import authenticate
from middleware import ROLE_CONTROLS_PROGRAMMER as CP
from middleware import ROLE_FINANCE_ADMIN as FA
from middleware import ROLE_PROJECT_ENGINEER as PE
from middleware import ROLE_SITE_SUPERVISOR as SS
from response import success, success_list
from services import calculations as calc
from services.domain import common_fields, pub, pubs, touch
from validation import as_num, as_str, body, paginate, pagination, req

bp = Blueprint("programs", __name__)

READ_ROLES = {FA, PE, CP, SS}


def get_program(program_id):
    p = store.programs.get(program_id)
    if p is None:
        raise not_found("Robot program not found")
    return p


@bp.post("/robotics/cell-projects/<project_id>/robot-programs")
def create_program(project_id):
    uid, _role = authenticate({CP})
    if project_id not in store.projects:
        raise not_found("Cell project not found")
    b = body()
    name = b.get("program_name")
    if isinstance(name, str):
        for existing in children("programs", "cell_project_id", project_id):
            if existing["program_name"] == name:
                raise ApiError(ERR_DUPLICATE_CODE, 409,
                               f"program_name '{name}' already exists for this project")
    program = {
        **common_fields(),
        "cell_project_id": project_id,
        "program_name": as_str(req(b, "program_name"), "program_name"),
        "dev_status": "OUTLINE",
        "sim_status": "UNSIMULATED",
        "last_sim_cycle_time_s": None,
        "sim_iteration_count": 0,
        "release_revision": 0,
        "_created_by": uid,
    }
    store.programs[program["id"]] = program
    return success(pub(program), 201)


@bp.get("/robotics/cell-projects/<project_id>/robot-programs")
def list_programs(project_id):
    authenticate(READ_ROLES)
    if project_id not in store.projects:
        raise not_found("Cell project not found")
    limit, offset = pagination()
    items = children("programs", "cell_project_id", project_id)
    dev_filter = request.args.get("dev_status")
    if dev_filter is not None:
        items = [p for p in items if p["dev_status"] == dev_filter]
    sim_filter = request.args.get("sim_status")
    if sim_filter is not None:
        items = [p for p in items if p["sim_status"] == sim_filter]
    page, total = paginate(items, limit, offset)
    return success_list(pubs(page), limit, offset, total)


@bp.get("/robotics/robot-programs/<program_id>")
def get_one_program(program_id):
    authenticate(READ_ROLES)
    return success(pub(get_program(program_id)))


@bp.post("/robotics/robot-programs/<program_id>/code-complete")
def code_complete(program_id):
    authenticate({CP})
    p = get_program(program_id)
    if p["dev_status"] == "OUTLINE":
        project = store.projects[p["cell_project_id"]]
        if project["status"] not in ("DESIGN", "BUILD"):
            raise invalid_state(
                "Marking an OUTLINE program code-complete requires project status "
                "DESIGN or BUILD")
    elif p["dev_status"] != "REWORK":
        raise invalid_state("Only OUTLINE or REWORK programs can be marked code-complete")
    p["dev_status"] = "CODED"
    touch(p)
    return success(pub(p))


@bp.post("/robotics/robot-programs/<program_id>/peer-review")
def peer_review(program_id):
    uid, _role = authenticate({CP})
    p = get_program(program_id)
    if p["dev_status"] != "CODED":
        raise invalid_state("Only a CODED program can be peer reviewed")
    if uid == p.get("_created_by"):
        raise ApiError(ERR_SEGREGATION_OF_DUTIES, 422,
                       "A programmer cannot review their own program")
    p["dev_status"] = "PEER_REVIEWED"
    touch(p)
    return success(pub(p))


@bp.post("/robotics/robot-programs/<program_id>/simulate")
def simulate(program_id):
    authenticate({CP})
    p = get_program(program_id)
    if p["dev_status"] not in ("CODED", "PEER_REVIEWED", "REWORK"):
        raise invalid_state(
            "Simulation requires dev_status CODED, PEER_REVIEWED, or REWORK")
    if p["sim_status"] not in ("UNSIMULATED", "SIM_FAILED"):
        raise invalid_state(
            "Simulation can only start from UNSIMULATED or SIM_FAILED")
    p["sim_status"] = "SIM_RUNNING"
    touch(p)
    return success(pub(p))


@bp.post("/robotics/robot-programs/<program_id>/simulate/record")
def simulate_record(program_id):
    authenticate({CP})
    p = get_program(program_id)
    if p["sim_status"] != "SIM_RUNNING":
        raise invalid_state("No simulation run is in progress")
    b = body()
    measured = as_num(req(b, "measured_sim_cycle_time_s"), "measured_sim_cycle_time_s")
    project = store.projects[p["cell_project_id"]]
    if calc.d(measured) <= calc.d(project["contracted_cycle_time_s"]):
        p["sim_status"] = "SIM_PASSED"
        p["last_sim_cycle_time_s"] = measured
    else:
        p["sim_status"] = "SIM_FAILED"
    p["sim_iteration_count"] += 1
    touch(p)
    return success(pub(p))


@bp.post("/robotics/robot-programs/<program_id>/release")
def release(program_id):
    authenticate({CP})
    p = get_program(program_id)
    if p["dev_status"] != "PEER_REVIEWED":
        raise invalid_state("Only a PEER_REVIEWED program can be released")
    if p["sim_status"] != "SIM_PASSED":
        raise invalid_state("Release requires sim_status SIM_PASSED")
    p["dev_status"] = "RELEASED"
    p["release_revision"] += 1
    touch(p)
    return success(pub(p))
