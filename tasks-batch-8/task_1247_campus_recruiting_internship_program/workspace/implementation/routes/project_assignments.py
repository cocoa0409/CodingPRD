"""ProjectAssignment routes."""

from flask import Blueprint, request, g

from db import db
from errors import (
    err_validation,
    err_forbidden,
    err_season_posture_forbidden,
    err_application_state_forbidden,
    err_project_state_forbidden,
    err_assignment_state_forbidden,
    err_mentor_conflict_of_interest,
    err_capability_missing,
    err_project_at_capacity,
    err_mentor_at_capacity,
    err_assignment_exists,
    err_final_evaluation_required,
)
from middleware import require_auth
from response import success_object, success_list
from services.domain import (
    get_season,
    get_application,
    get_employee,
    get_intern_project,
    get_project_assignment,
    project_assignment_view,
    assignment_season,
)
from utils import (
    parse_pagination,
    require_field,
    require_enum,
    stamp_new,
    touch,
)

bp = Blueprint("project_assignments", __name__)


def _find_assignment_by_application(aid):
    for a in db.project_assignments.values():
        if a["application_id"] == aid:
            return a
    return None


@bp.route("/intern-projects/<pid>/project-assignments", methods=["POST"])
@require_auth(["Recruiter"])
def create_project_assignment(pid):
    project = get_intern_project(pid)
    season = get_season(project["season_id"])
    payload = request.get_json(silent=True) or {}
    application_id = require_field(payload, "application_id")
    if not isinstance(application_id, str):
        raise err_validation("application_id must be a string")
    mentor_id = require_field(payload, "mentor_id")
    if not isinstance(mentor_id, str):
        raise err_validation("mentor_id must be a string")
    application = get_application(application_id)
    mentor = get_employee(mentor_id)

    # Posture
    if season["status"] != "INTERN_ACTIVE":
        raise err_season_posture_forbidden()
    # Application state
    if application["status"] != "ACCEPTED":
        raise err_application_state_forbidden("project assignment requires ACCEPTED application")
    # Application must be in this season (nested ownership sanity)
    if application["season_id"] != project["season_id"]:
        from errors import err_not_found
        raise err_not_found(f"Application {application_id} not in project's season")
    # Mentor must belong to the same season
    if mentor["season_id"] != project["season_id"]:
        from errors import err_not_found
        raise err_not_found(f"Employee {mentor_id} not in project's season")
    # Project state
    if project["status"] != "OPEN":
        raise err_project_state_forbidden()
    # SoD: mentor must not have submitted any evaluation on any slot of this application
    slot_ids = [
        s["id"] for s in db.interview_slots.values()
        if s["application_id"] == application_id
    ]
    slot_set = set(slot_ids)
    for ev in db.evaluations.values():
        if ev["interview_slot_id"] in slot_set and ev["evaluator_id"] == mentor_id:
            raise err_mentor_conflict_of_interest()
    # Capability
    if not mentor["can_mentor"]:
        raise err_capability_missing("can_mentor is required")
    # Capacities: project first, then mentor
    if project["assigned_count"] >= project["capacity"]:
        raise err_project_at_capacity()
    if mentor["assigned_intern_count"] >= mentor["max_interns"]:
        raise err_mentor_at_capacity()
    # Uniqueness
    if _find_assignment_by_application(application_id) is not None:
        raise err_assignment_exists()

    a = {
        "application_id": application_id,
        "intern_project_id": pid,
        "mentor_id": mentor_id,
        "status": "ACTIVE",
        "return_offer_decision": "NONE",
        "return_offer_outcome": "NONE",
    }
    stamp_new(a)
    db.project_assignments[a["id"]] = a
    project["assigned_count"] += 1
    touch(project)
    mentor["assigned_intern_count"] += 1
    touch(mentor)
    return success_object(project_assignment_view(a), 201)


@bp.route("/project-assignments/<aid>", methods=["GET"])
@require_auth(["RecruitingAdmin", "Recruiter", "Mentor"])
def get_one_assignment(aid):
    a = get_project_assignment(aid)
    if g.role == "Mentor" and g.user_id != a["mentor_id"]:
        raise err_forbidden("Mentor may read only own assignments")
    return success_object(project_assignment_view(a))


@bp.route("/applications/<aid>/project-assignments", methods=["GET"])
@require_auth(["RecruitingAdmin", "Recruiter", "Candidate"])
def list_application_assignments(aid):
    app = get_application(aid)
    if g.role == "Candidate" and g.user_id != app["candidate_id"]:
        raise err_forbidden("Candidate may read only its own assignments")
    limit, offset = parse_pagination(request.args)
    items = [a for a in db.project_assignments.values() if a["application_id"] == aid]
    items.sort(key=lambda a: a["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([project_assignment_view(a) for a in page], total, limit, offset)


@bp.route("/project-assignments/<aid>/unassign", methods=["POST"])
@require_auth(["Recruiter"])
def unassign(aid):
    a = get_project_assignment(aid)
    season = assignment_season(a)
    if season["status"] != "INTERN_ACTIVE":
        raise err_season_posture_forbidden()
    if a["status"] != "ACTIVE":
        raise err_assignment_state_forbidden("unassign requires ACTIVE")
    a["status"] = "UNASSIGNED"
    touch(a)
    project = get_intern_project(a["intern_project_id"])
    project["assigned_count"] -= 1
    touch(project)
    mentor = get_employee(a["mentor_id"])
    mentor["assigned_intern_count"] -= 1
    touch(mentor)
    # return_offer_decision and return_offer_outcome frozen (no changes)
    return success_object(project_assignment_view(a))


@bp.route("/project-assignments/<aid>/complete", methods=["POST"])
@require_auth(["Recruiter"])
def complete_assignment(aid):
    a = get_project_assignment(aid)
    season = assignment_season(a)
    if season["status"] != "INTERN_ACTIVE":
        raise err_season_posture_forbidden()
    if a["status"] != "ACTIVE":
        raise err_assignment_state_forbidden("complete requires ACTIVE")
    # FINAL evaluation must exist
    has_final = any(
        ev["project_assignment_id"] == aid and ev["eval_type"] == "FINAL"
        for ev in db.intern_evaluations.values()
    )
    if not has_final:
        raise err_final_evaluation_required()
    a["status"] = "COMPLETED"
    touch(a)
    season["completed_assignments_count"] += 1
    touch(season)
    # Flip candidate is_alumnus
    application = get_application(a["application_id"])
    candidate = db.candidates.get(application["candidate_id"])
    if candidate is not None and not candidate["is_alumnus"]:
        candidate["is_alumnus"] = True
        touch(candidate)
    # Capacity counts unchanged
    return success_object(project_assignment_view(a))
