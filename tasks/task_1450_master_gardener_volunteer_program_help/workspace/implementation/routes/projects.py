"""CommunityProject endpoints: propose, amend (OCC), submit, approve, request-revision, reject, close."""

from flask import request, Blueprint

import db
import util
from util import D, round_half_up, is_multiple_quarter
from middleware import auth_context
from errors import raise_err
from response import success_object, success_list
from services import calculations as calc

bp = Blueprint("projects", __name__)

ALL_ROLES = ["ProgramCoordinator", "Volunteer", "Specialist"]
PC = ["ProgramCoordinator"]


def get_project_or_404(project_id):
    p = db.community_projects.get(project_id)
    if p is None:
        raise_err("ERR_NOT_FOUND", "CommunityProject not found")
    return p


def _validate_estimated_hours(v):
    if not isinstance(v, (int, float)) or isinstance(v, bool):
        raise_err("ERR_INVALID_REQUEST", "estimated_hours_per_volunteer must be a number")
    d = D(v)
    if d <= 0 or not is_multiple_quarter(d):
        raise_err("ERR_INVALID_FIELD_VALUE",
                  "estimated_hours_per_volunteer must be > 0 and a multiple of 0.25")
    return float(d)


@bp.route("/projects", methods=["POST"])
def create_project():
    user_id, role = auth_context(["Volunteer"])
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise_err("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    for f in ("cycle_id", "organizer_volunteer_id", "title", "description", "estimated_hours_per_volunteer"):
        if f not in body:
            raise_err("ERR_INVALID_REQUEST", f"Missing required field: {f}")
    for f in ("cycle_id", "organizer_volunteer_id", "title", "description"):
        if not isinstance(body[f], str) or not body[f]:
            raise_err("ERR_INVALID_REQUEST", f"{f} must be a non-empty string")
    est = _validate_estimated_hours(body["estimated_hours_per_volunteer"])

    vol = db.volunteers.get(body["organizer_volunteer_id"])
    if vol is None:
        raise_err("ERR_NOT_FOUND", "organizer_volunteer_id does not resolve")
    if user_id != vol["id"]:
        raise_err("ERR_NOT_RESOURCE_OWNER", "Volunteers may only propose their own projects")
    cycle = db.program_cycles.get(body["cycle_id"])
    if cycle is None:
        raise_err("ERR_NOT_FOUND", "cycle_id does not resolve")
    if cycle["status"] != "OPEN":
        raise_err("ERR_CYCLE_NOT_OPEN", "Project creation requires an OPEN cycle")
    if vol["status"] != "ACTIVE":
        raise_err("ERR_VOLUNTEER_NOT_ACTIVE", "Only an ACTIVE volunteer may propose a project")

    project = util.new_resource({
        "cycle_id": cycle["id"],
        "organizer_volunteer_id": vol["id"],
        "title": body["title"],
        "description": body["description"],
        "estimated_hours_per_volunteer": est,
        "max_creditable_hours_per_volunteer": None,
        "approved_by_user_id": None,
        "feedback": None,
        "status": "DRAFT",
    })
    db.community_projects[project["id"]] = project
    return success_object(project, 201)


@bp.route("/projects", methods=["GET"])
def list_projects():
    auth_context(ALL_ROLES)
    items = list(db.community_projects.values())
    for param in ("cycle_id", "organizer_volunteer_id", "status"):
        v = request.args.get(param)
        if v is not None:
            items = [p for p in items if p.get(param) == v]
    items = util.sort_created(items)
    limit, offset = util.paginate(items, request.args)
    return success_list(items[offset:offset + limit], len(items), limit, offset)


@bp.route("/projects/<projectId>", methods=["GET"])
def get_project(projectId):
    auth_context(ALL_ROLES)
    return success_object(get_project_or_404(projectId))


@bp.route("/projects/<projectId>", methods=["PUT"])
def amend_project(projectId):
    user_id, role = auth_context(["Volunteer"])
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise_err("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    if "expected_project_version" not in body:
        raise_err("ERR_INVALID_REQUEST", "expected_project_version is required")
    if not isinstance(body["expected_project_version"], int) or isinstance(body["expected_project_version"], bool):
        raise_err("ERR_INVALID_REQUEST", "expected_project_version must be an integer")
    # schema on supplied fields
    updates = {}
    if "title" in body:
        if not isinstance(body["title"], str) or not body["title"]:
            raise_err("ERR_INVALID_REQUEST", "title must be a non-empty string")
        updates["title"] = body["title"]
    if "description" in body:
        if not isinstance(body["description"], str) or not body["description"]:
            raise_err("ERR_INVALID_REQUEST", "description must be a non-empty string")
        updates["description"] = body["description"]
    if "estimated_hours_per_volunteer" in body:
        updates["estimated_hours_per_volunteer"] = _validate_estimated_hours(body["estimated_hours_per_volunteer"])

    project = get_project_or_404(projectId)
    if user_id != project["organizer_volunteer_id"]:
        raise_err("ERR_NOT_RESOURCE_OWNER", "Only the organizer may amend this project")
    if body["expected_project_version"] != project["version"]:
        raise_err("ERR_STALE_PROJECT_VERSION",
                  "expected_project_version does not match the project's current version")
    if project["status"] not in ("DRAFT", "REVISION_REQUESTED"):
        raise_err("ERR_PROJECT_NOT_EDITABLE", "Project may only be amended while DRAFT or REVISION_REQUESTED")
    for k, v in updates.items():
        project[k] = v
    util.touch(project)
    return success_object(project)


@bp.route("/projects/<projectId>/submit", methods=["POST"])
def submit_project(projectId):
    user_id, role = auth_context(["Volunteer"])
    project = get_project_or_404(projectId)
    if user_id != project["organizer_volunteer_id"]:
        raise_err("ERR_NOT_RESOURCE_OWNER", "Only the organizer may submit this project")
    if project["status"] not in ("DRAFT", "REVISION_REQUESTED"):
        raise_err("ERR_PROJECT_NOT_EDITABLE", "Submit requires DRAFT or REVISION_REQUESTED")
    project["status"] = "UNDER_REVIEW"
    util.touch(project)
    return success_object(project)


@bp.route("/projects/<projectId>/approve", methods=["POST"])
def approve_project(projectId):
    user_id, role = auth_context(PC)
    project = get_project_or_404(projectId)
    if project["status"] != "UNDER_REVIEW":
        raise_err("ERR_PROJECT_NOT_UNDER_REVIEW", "Approve requires UNDER_REVIEW")
    project["approved_by_user_id"] = user_id
    cap = round_half_up(D(project["estimated_hours_per_volunteer"]) * D("1.25"), 2)
    project["max_creditable_hours_per_volunteer"] = float(min(cap, D("20.0")))
    project["status"] = "APPROVED"
    util.touch(project)
    return success_object(project)


@bp.route("/projects/<projectId>/request-revision", methods=["POST"])
def request_revision(projectId):
    auth_context(PC)
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise_err("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    if "feedback" not in body or not isinstance(body.get("feedback"), str):
        raise_err("ERR_INVALID_REQUEST", "feedback is required")
    project = get_project_or_404(projectId)
    if project["status"] != "UNDER_REVIEW":
        raise_err("ERR_PROJECT_NOT_UNDER_REVIEW", "Request-revision requires UNDER_REVIEW")
    project["feedback"] = body["feedback"]
    project["status"] = "REVISION_REQUESTED"
    util.touch(project)
    return success_object(project)


@bp.route("/projects/<projectId>/reject", methods=["POST"])
def reject_project(projectId):
    auth_context(PC)
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise_err("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    if "reason" not in body or not isinstance(body.get("reason"), str):
        raise_err("ERR_INVALID_REQUEST", "reason is required")
    project = get_project_or_404(projectId)
    if project["status"] != "UNDER_REVIEW":
        raise_err("ERR_PROJECT_NOT_UNDER_REVIEW", "Reject requires UNDER_REVIEW")
    project["feedback"] = body["reason"]
    project["status"] = "REJECTED"
    util.touch(project)
    return success_object(project)


@bp.route("/projects/<projectId>/close", methods=["POST"])
def close_project(projectId):
    user_id, role = auth_context(PC)
    project = get_project_or_404(projectId)
    if project["status"] != "APPROVED":
        raise_err("ERR_PROJECT_NOT_APPROVED", "Close requires APPROVED")
    # segregation of duties
    if user_id == project["approved_by_user_id"]:
        raise_err("ERR_SEGREGATION_OF_DUTIES",
                  "The coordinator who approved the project may not close it")
    project["status"] = "CLOSED"
    util.touch(project)
    # cascade link 1: void PENDING project-sourced entries
    affected = set()
    for e in db.credit_entries.values():
        if e["source_type"] == "PROJECT" and e["source_id"] == project["id"] and e["status"] == "PENDING":
            e["status"] = "VOIDED"
            util.touch(e)
            affected.add((e["volunteer_id"], e["cycle_id"]))
    # cascade link 2: recompute affected records
    for (vid, cid) in affected:
        rec = calc.record_for(vid, cid)
        if rec is not None and rec["status"] == "PENDING":
            calc.recompute_record(rec)
    return success_object(project)
