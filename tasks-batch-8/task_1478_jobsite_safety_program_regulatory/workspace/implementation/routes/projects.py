from flask import Blueprint, request

from db import store
from helpers import (
    require_roles,
    body,
    reject_unknown,
    f_str,
    f_int,
    ok,
    paginate,
    invalid,
)
from services import (
    get_project,
    new_entity,
    ser_project,
    osha_summary,
)

bp = Blueprint("projects", __name__)

ALL_ROLES = (
    "SafetyManager",
    "SiteSuperintendent",
    "SafetyInspector",
    "SubcontractorRep",
    "ComplianceAuditor",
)


@bp.route("/safety/projects", methods=["POST"])
def create_project():
    require_roles("SafetyManager")
    b = body()
    reject_unknown(b, {"name", "location", "annual_hours_worked"})
    name = f_str(b, "name")
    location = f_str(b, "location")
    hours = f_int(b, "annual_hours_worked", min_v=1)
    p = new_entity()
    p.update(
        {
            "name": name,
            "location": location,
            "annual_hours_worked": hours,
            "safety_posture": "NORMAL",
            "current_active_plan_id": None,
        }
    )
    store.projects[p["id"]] = p
    return ok(ser_project(p), 201)


@bp.route("/safety/projects", methods=["GET"])
def list_projects():
    require_roles(*ALL_ROLES)
    return paginate(list(store.projects.values()), ser_project)


@bp.route("/safety/projects/<projectId>/osha-summary", methods=["GET"])
def project_osha_summary(projectId):
    require_roles("SafetyManager", "ComplianceAuditor")
    project = get_project(projectId)
    raw_year = request.args.get("year")
    if raw_year is None:
        invalid("Missing required query parameter: year")
    try:
        year = int(raw_year)
    except (TypeError, ValueError):
        invalid("Query parameter year must be an integer")
    return ok(osha_summary(project, year))


@bp.route("/safety/projects/<projectId>", methods=["GET"])
def get_one_project(projectId):
    require_roles(*ALL_ROLES)
    return ok(ser_project(get_project(projectId)))
