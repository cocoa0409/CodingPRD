"""ServiceProject endpoints: propose, vet, match, lock, cancel."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_err,
    ERR_PROJECT_NOT_FOUND,
    ERR_NONPROFIT_NOT_FOUND,
    ERR_EVENT_NOT_FOUND,
    ERR_FORBIDDEN_ROLE,
    ERR_NONPROFIT_SUSPENDED,
    ERR_INVALID_PROJECT_TRANSITION,
    ERR_EVENT_STATE_FORBIDS_WRITE,
    ERR_MIN_VOLUNTEERS_NOT_MET,
    ERR_INSUFFICIENT_SUPERVISION,
    ERR_SITE_PREP_INCOMPLETE,
)
from middleware import authenticate, body
from response import success_object, success_list
from services import calc
from services.cascades import project_cancel_cascade
from services.core import mint, bump, touch, refresh_event, ser_project, sort_entities
from validate import req_string, req_int, opt_str_list, check_range

bp = Blueprint("projects", __name__)

CEM = ["CommunityEngagementManager"]


def load_project(project_id):
    p = db.projects.get(project_id)
    if p is None:
        raise_err(ERR_PROJECT_NOT_FOUND, "service project not found")
    return p


@bp.post("/service-projects")
def create_project():
    uid, role, _ = authenticate(["NonprofitCoordinator"])
    data = body()
    nonprofit_id = req_string(data, "nonprofit_id")
    title = req_string(data, "title")
    min_v = req_int(data, "min_volunteers")
    max_v = req_int(data, "max_volunteers")
    skills = opt_str_list(data, "required_skills")
    # ownership (pipeline step 2): coordinator's X-User-ID must equal nonprofit_id
    if uid != nonprofit_id:
        raise_err(ERR_FORBIDDEN_ROLE, "nonprofit_id must equal the acting coordinator's X-User-ID")
    # body FK existence (step 5)
    partner = db.partners.get(nonprofit_id)
    if partner is None:
        raise_err(ERR_NONPROFIT_NOT_FOUND, "nonprofit partner not found")
    # state (step 6): suspended partner cannot source new work
    if partner["status"] == "SUSPENDED":
        raise_err(ERR_NONPROFIT_SUSPENDED, "partner is SUSPENDED")
    # range validation (step 11)
    check_range(min_v >= 1, "min_volunteers must be >= 1")
    check_range(max_v >= min_v, "max_volunteers must be >= min_volunteers")
    p = mint()
    p.update(
        {
            "nonprofit_id": nonprofit_id,
            "event_id": None,
            "title": title,
            "required_skills": skills,
            "min_volunteers": min_v,
            "max_volunteers": max_v,
            "status": "PROPOSED",
        }
    )
    db.projects[p["id"]] = p
    return success_object(ser_project(p), 201)


@bp.get("/service-projects")
def list_projects():
    authenticate(["Any"])
    items = list(db.projects.values())
    for param in ("nonprofit_id", "event_id", "status"):
        val = request.args.get(param)
        if val is not None:
            items = [p for p in items if str(p.get(param)) == val]
    return success_list([ser_project(p) for p in sort_entities(items)])


@bp.get("/service-projects/<projectId>")
def get_project(projectId):
    authenticate(["Any"])
    return success_object(ser_project(load_project(projectId)))


@bp.post("/service-projects/<projectId>/vet")
def vet_project(projectId):
    authenticate(CEM)
    p = load_project(projectId)
    if p["status"] != "PROPOSED":
        raise_err(ERR_INVALID_PROJECT_TRANSITION, "only a PROPOSED project can be vetted")
    partner = db.partners.get(p["nonprofit_id"])
    if partner is not None and partner["status"] == "SUSPENDED":
        raise_err(ERR_NONPROFIT_SUSPENDED, "partner is SUSPENDED")
    p["status"] = "VETTED"
    bump(p)
    return success_object(ser_project(p))


@bp.post("/service-projects/<projectId>/match")
def match_project(projectId):
    authenticate(CEM)
    p = load_project(projectId)
    data = body()
    event_id = req_string(data, "event_id")
    ev = db.events.get(event_id)
    if ev is None:
        raise_err(ERR_EVENT_NOT_FOUND, "service event not found")
    if p["status"] != "VETTED":
        raise_err(ERR_INVALID_PROJECT_TRANSITION, "only a VETTED project can be matched")
    partner = db.partners.get(p["nonprofit_id"])
    if partner is not None and partner["status"] == "SUSPENDED":
        raise_err(ERR_NONPROFIT_SUSPENDED, "partner is SUSPENDED")
    if ev["status"] not in ("PLANNING", "REGISTRATION_OPEN", "REGISTRATION_LOCKED"):
        raise_err(ERR_EVENT_STATE_FORBIDS_WRITE, "event state forbids matching")
    p["status"] = "MATCHED"
    p["event_id"] = ev["id"]
    bump(p)
    refresh_event(ev)
    return success_object(ser_project(p))


@bp.post("/service-projects/<projectId>/lock")
def lock_project(projectId):
    authenticate(CEM)
    p = load_project(projectId)
    if p["status"] != "MATCHED":
        raise_err(ERR_INVALID_PROJECT_TRANSITION, "only a MATCHED project can be locked")
    ev = db.events.get(p["event_id"])
    if ev is None or ev["status"] not in ("REGISTRATION_OPEN", "REGISTRATION_LOCKED"):
        raise_err(ERR_EVENT_STATE_FORBIDS_WRITE, "event must be REGISTRATION_OPEN or REGISTRATION_LOCKED")
    # PRD 3.3 explicit order: min volunteers -> supervision -> site prep
    if calc.project_confirmed_count(p) < p["min_volunteers"]:
        raise_err(ERR_MIN_VOLUNTEERS_NOT_MET, "confirmed_volunteer_count below min_volunteers")
    required = calc.supervision_requirement(p)
    if required < 1 or calc.active_staff_leads(p) < required:
        raise_err(ERR_INSUFFICIENT_SUPERVISION, "insufficient active staff leads")
    if not calc.site_prep_complete(p):
        raise_err(ERR_SITE_PREP_INCOMPLETE, "site prep is not complete")
    p["status"] = "LOCKED"
    bump(p)
    refresh_event(ev)
    return success_object(ser_project(p))


@bp.post("/service-projects/<projectId>/cancel")
def cancel_project(projectId):
    authenticate(CEM)
    p = load_project(projectId)
    if p["status"] not in ("PROPOSED", "VETTED", "MATCHED", "LOCKED"):
        raise_err(ERR_INVALID_PROJECT_TRANSITION, "project cannot be cancelled from its current status")
    old_event = db.events.get(p["event_id"]) if p["event_id"] else None
    project_cancel_cascade(p)
    p["status"] = "CANCELLED"
    bump(p)
    if old_event is not None:
        refresh_event(old_event)
    return success_object(ser_project(p))
