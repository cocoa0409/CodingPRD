"""SupervisionAssignment endpoints."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_err,
    ERR_SUPERVISION_NOT_FOUND,
    ERR_PROJECT_NOT_FOUND,
    ERR_VOLUNTEER_NOT_FOUND,
    ERR_FORBIDDEN_ROLE,
    ERR_INVALID_PROJECT_TRANSITION,
    ERR_INVALID_SUPERVISION_TRANSITION,
    ERR_LEAD_NOT_QUALIFIED,
    ERR_ACTIVE_SUPERVISION_EXISTS,
)
from middleware import authenticate, body
from response import success_object, success_list
from services.core import mint, bump, touch, refresh_event, maybe_demote_project, ser_assignment, sort_entities
from validate import req_string

bp = Blueprint("supervision", __name__)


def load_assignment(assignment_id):
    a = db.assignments.get(assignment_id)
    if a is None:
        raise_err(ERR_SUPERVISION_NOT_FOUND, "supervision assignment not found")
    return a


@bp.post("/supervision-assignments")
def create_assignment():
    authenticate(["CommunityEngagementManager"])
    data = body()
    project_id = req_string(data, "project_id")
    lead_id = req_string(data, "lead_volunteer_id")
    # body FK existence (step 5)
    project = db.projects.get(project_id)
    if project is None:
        raise_err(ERR_PROJECT_NOT_FOUND, "service project not found")
    lead = db.volunteers.get(lead_id)
    if lead is None:
        raise_err(ERR_VOLUNTEER_NOT_FOUND, "lead volunteer not found")
    # state (step 6)
    if project["status"] not in ("MATCHED", "LOCKED"):
        raise_err(ERR_INVALID_PROJECT_TRANSITION, "project must be MATCHED or LOCKED to staff")
    # supervision safety (step 8): lead eligible and not a participant on the project
    has_own_registration = any(
        r["project_id"] == project["id"]
        and r["volunteer_id"] == lead["id"]
        and r["rsvp_status"] != "CANCELLED"
        for r in db.registrations.values()
    )
    if not lead["is_staff_lead"] or has_own_registration:
        raise_err(ERR_LEAD_NOT_QUALIFIED, "lead must be staff-lead eligible and not registered on this project")
    # uniqueness (step 11)
    for a in db.assignments.values():
        if (
            a["project_id"] == project["id"]
            and a["lead_volunteer_id"] == lead["id"]
            and a["status"] == "ACTIVE"
        ):
            raise_err(ERR_ACTIVE_SUPERVISION_EXISTS, "an ACTIVE assignment already exists for this project and lead")
    a = mint()
    a.update(
        {
            "project_id": project["id"],
            "event_id": project["event_id"],
            "lead_volunteer_id": lead["id"],
            "status": "ACTIVE",
        }
    )
    db.assignments[a["id"]] = a
    touch(project)
    ev = db.events.get(project["event_id"]) if project["event_id"] else None
    if ev is not None:
        refresh_event(ev)
    return success_object(ser_assignment(a), 201)


@bp.get("/supervision-assignments")
def list_assignments():
    authenticate(["Any"])
    items = list(db.assignments.values())
    for param in ("project_id", "event_id", "lead_volunteer_id", "status"):
        val = request.args.get(param)
        if val is not None:
            items = [a for a in items if str(a.get(param)) == val]
    return success_list([ser_assignment(a) for a in sort_entities(items)])


@bp.get("/supervision-assignments/<assignmentId>")
def get_assignment(assignmentId):
    authenticate(["Any"])
    return success_object(ser_assignment(load_assignment(assignmentId)))


@bp.post("/supervision-assignments/<assignmentId>/withdraw")
def withdraw_assignment(assignmentId):
    uid, role, _ = authenticate(["CommunityEngagementManager", "StaffLead"])
    a = load_assignment(assignmentId)
    if role == "StaffLead" and uid != a["lead_volunteer_id"]:
        raise_err(ERR_FORBIDDEN_ROLE, "a staff lead may only withdraw their own assignment")
    if a["status"] != "ACTIVE":
        raise_err(ERR_INVALID_SUPERVISION_TRANSITION, "only an ACTIVE assignment can be withdrawn")
    a["status"] = "WITHDRAWN"
    bump(a)
    project = db.projects.get(a["project_id"])
    if project is not None:
        maybe_demote_project(project)
        touch(project)
        ev = db.events.get(project["event_id"]) if project["event_id"] else None
        if ev is not None:
            refresh_event(ev)
    return success_object(ser_assignment(a))
