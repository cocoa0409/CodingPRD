"""Visits, crew assignment, and visit execution (PRD §3.7, §3.8)."""
from datetime import timezone

from flask import Blueprint, request

import clock
import db
import helpers as h
from errors import err
from middleware import authenticate, authorize
from response import success, paginated
from services import domain

bp = Blueprint("visits", __name__)

READ_ROLES = {"PlatformAdmin", "SystemsDesigner", "ProjectManager", "SupportEngineer", "LowVoltageTech", "Client"}
ASSIGN_READ_ROLES = {"PlatformAdmin", "ProjectManager", "LowVoltageTech"}

VISIT_CREATE_PROJECT_STATES = {"ACCEPTED", "PROVISIONING", "SCHEDULED", "INSTALLING", "COMMISSIONED", "ACTIVE"}
NON_TERMINAL_VISIT = {"PLANNED", "CONFIRMED", "IN_PROGRESS"}


def _visit_in_project(project_id, visit_id):
    h.get_or_404(db.projects, project_id)
    visit = db.visits.get(visit_id)
    if visit is None or visit["project_id"] != project_id:
        raise err("ERR_NOT_FOUND", "Visit not found in project")
    return visit


def _parse_window(start, end):
    """Return (start_dt, end_dt) as aware UTC; end strictly after start."""
    s = h.parse_iso(start, "window_start")
    e = h.parse_iso(end, "window_end")
    if not (e > s):
        raise err("ERR_INVALID_REQUEST", "window_end must be strictly after window_start")
    return s, e


def _wstart(visit):
    return h.parse_iso(visit["window_start"], "window_start")


def _wend(visit):
    return h.parse_iso(visit["window_end"], "window_end")


def _closed_overlap(a_start, a_end, b_start, b_end):
    """Closed-interval overlap: touching endpoints conflict."""
    return a_start <= b_end and b_start <= a_end


def _halfopen_overlap(a_start, a_end, b_start, b_end):
    """Half-open [start, end) overlap: touching endpoints do NOT conflict."""
    return a_start < b_end and b_start < a_end


# ---------------------------------------------------------------------------
# Create visit (PRD §3.7)
# ---------------------------------------------------------------------------
@bp.post("/projects/<project_id>/visits")
def create_visit(project_id):
    _, role = authenticate()
    authorize(role, {"ProjectManager"})
    project = h.get_or_404(db.projects, project_id)
    body = h.get_body()
    window_start_raw = h.require_str(body, "window_start")
    window_end_raw = h.require_str(body, "window_end")
    visit_kind = h.require_enum(body, "visit_kind", h.VISIT_KINDS)
    crew_size_required = h.require_int(body, "crew_size_required", minimum=1)
    start_dt, end_dt = _parse_window(window_start_raw, window_end_raw)
    # state (priority 7): project must be in allowed states
    if project["status"] not in VISIT_CREATE_PROJECT_STATES:
        raise err("ERR_INVALID_STATE", "Project state does not permit visit creation")
    # time conflict (priority 10): closed-interval overlap with non-terminal visits
    for v in db.visits.values():
        if v["project_id"] == project_id and v["status"] in NON_TERMINAL_VISIT:
            if _closed_overlap(start_dt, end_dt, _wstart(v), _wend(v)):
                raise err("ERR_VISIT_TIME_CONFLICT", "Visit window overlaps an existing visit")
    entity = {
        "project_id": project_id,
        "region_code": project["region_code"],
        "window_start": window_start_raw,
        "window_end": window_end_raw,
        "visit_kind": visit_kind,
        "status": "PLANNED",
        "crew_size_required": crew_size_required,
        "assigned_crew_count": 0,
    }
    db.stamp_create(entity)
    db.visits[entity["id"]] = entity
    return success(h.public(entity), status=201)


@bp.get("/projects/<project_id>/visits")
def list_visits(project_id):
    _, role = authenticate()
    authorize(role, READ_ROLES)
    h.get_or_404(db.projects, project_id)
    limit, offset = h.parse_pagination()
    visit_kind = request.args.get("visit_kind")
    status = request.args.get("status")
    items = [v for v in db.visits.values() if v["project_id"] == project_id]
    if visit_kind is not None:
        items = [v for v in items if v["visit_kind"] == visit_kind]
    if status is not None:
        items = [v for v in items if v["status"] == status]
    items = h.sort_by_creation(items)
    page, total = h.paginate(items, limit, offset)
    return paginated([h.public(v) for v in page], limit, offset, total)


@bp.get("/projects/<project_id>/visits/<visit_id>")
def get_visit_nested(project_id, visit_id):
    _, role = authenticate()
    authorize(role, READ_ROLES)
    visit = _visit_in_project(project_id, visit_id)
    return success(h.public(visit))


@bp.get("/visits/<visit_id>")
def get_visit_flat(visit_id):
    _, role = authenticate()
    authorize(role, READ_ROLES)
    visit = h.get_or_404(db.visits, visit_id)
    return success(h.public(visit))


@bp.get("/visits/<visit_id>/assignments")
def list_visit_assignments_flat(visit_id):
    _, role = authenticate()
    authorize(role, ASSIGN_READ_ROLES)
    h.get_or_404(db.visits, visit_id)
    return _list_assignments_for_visit(visit_id)


@bp.get("/projects/<project_id>/visits/<visit_id>/assignments")
def list_visit_assignments_nested(project_id, visit_id):
    _, role = authenticate()
    authorize(role, ASSIGN_READ_ROLES)
    _visit_in_project(project_id, visit_id)
    return _list_assignments_for_visit(visit_id)


def _list_assignments_for_visit(visit_id):
    limit, offset = h.parse_pagination()
    status = request.args.get("status")
    items = [a for a in db.assignments.values() if a["visit_id"] == visit_id]
    if status is not None:
        items = [a for a in items if a["status"] == status]
    items = h.sort_by_creation(items)
    page, total = h.paginate(items, limit, offset)
    return paginated([h.public(a) for a in page], limit, offset, total)


# ---------------------------------------------------------------------------
# Assign crew (OCC on visit version) — PRD §3.7
# ---------------------------------------------------------------------------
@bp.post("/projects/<project_id>/visits/<visit_id>/assignments")
def create_assignment(project_id, visit_id):
    _, role = authenticate()
    authorize(role, {"ProjectManager"})
    visit = _visit_in_project(project_id, visit_id)
    body = h.get_body()
    crew_member_id = h.require_str(body, "crew_member_id")
    expected_version = h.require_int(body, "expected_visit_version")
    # priority 6 referential integrity: crew member must be real
    crew = db.crew_members.get(crew_member_id)
    if crew is None:
        raise err("ERR_REFERENTIAL_INTEGRITY", "crew_member_id does not reference a crew member")
    # priority 11 crew assignability: active then region
    if not crew["active"]:
        raise err("ERR_CREW_INACTIVE", "Crew member is not active")
    if crew["region_code"] != visit["region_code"]:
        raise err("ERR_CREW_REGION_MISMATCH", "Crew member does not serve the visit's region")
    # priority 12 crew time-overlap (half-open) against member's other ACTIVE assignments
    v_start, v_end = _wstart(visit), _wend(visit)
    for a in db.assignments.values():
        if a["crew_member_id"] == crew_member_id and a["status"] == "ACTIVE":
            other = db.visits.get(a["visit_id"])
            if other is None:
                continue
            if _halfopen_overlap(v_start, v_end, _wstart(other), _wend(other)):
                raise err("ERR_CREW_TIME_CONFLICT", "Crew member has an overlapping assignment")
    # priority 13 daily cap
    target_day = v_start.astimezone(timezone.utc).date()
    load = 0
    for a in db.assignments.values():
        if a["crew_member_id"] == crew_member_id and a["status"] == "ACTIVE":
            other = db.visits.get(a["visit_id"])
            if other is None:
                continue
            if _wstart(other).astimezone(timezone.utc).date() == target_day:
                load += 1
    if load + 1 > crew["daily_visit_cap"]:
        raise err("ERR_CREW_DAILY_CAP_EXCEEDED", "Crew member daily visit cap exceeded")
    # priority 15 OCC last
    if expected_version != visit["version"]:
        raise err("ERR_STALE_VERSION", "expected_visit_version does not match current visit version")

    entity = {
        "visit_id": visit_id,
        "crew_member_id": crew_member_id,
        "status": "ACTIVE",
    }
    db.stamp_create(entity)
    db.assignments[entity["id"]] = entity
    # Recompute assigned_crew_count and bump the visit's version by exactly one
    # (PRD §3.7). Set the count directly so we touch the visit once.
    count = sum(
        1 for a in db.assignments.values()
        if a["visit_id"] == visit_id and a["status"] == "ACTIVE"
    )
    visit["assigned_crew_count"] = count
    db.touch(visit)
    return success(h.public(entity), status=201)


@bp.post("/projects/<project_id>/visits/<visit_id>/assignments/<assignment_id>/release")
def release_assignment(project_id, visit_id, assignment_id):
    _, role = authenticate()
    authorize(role, {"ProjectManager"})
    visit = _visit_in_project(project_id, visit_id)
    a = db.assignments.get(assignment_id)
    if a is None or a["visit_id"] != visit_id:
        raise err("ERR_NOT_FOUND", "Assignment not found on visit")
    if a["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Only an ACTIVE assignment may be released")
    a["status"] = "RELEASED"
    db.touch(a)
    domain.recompute_visit_crew_count(visit)
    return success(h.public(a))


# ---------------------------------------------------------------------------
# Visit execution (PRD §3.8)
# ---------------------------------------------------------------------------
@bp.post("/projects/<project_id>/visits/<visit_id>/confirm")
def confirm_visit(project_id, visit_id):
    _, role = authenticate()
    authorize(role, {"ProjectManager"})
    visit = _visit_in_project(project_id, visit_id)
    if visit["status"] != "PLANNED":
        raise err("ERR_INVALID_STATE", "Only a PLANNED visit may be confirmed")
    # staffing gate
    if visit["assigned_crew_count"] < visit["crew_size_required"]:
        raise err("ERR_UNDERSTAFFED_VISIT", "Visit is understaffed")
    # commission cert gate
    if visit["visit_kind"] == "COMMISSION":
        ok = False
        for a in db.assignments.values():
            if a["visit_id"] == visit_id and a["status"] == "ACTIVE":
                crew = db.crew_members.get(a["crew_member_id"])
                if crew and crew["cert_level"] in ("JOURNEYMAN", "MASTER"):
                    ok = True
                    break
        if not ok:
            raise err("ERR_CERT_TOO_LOW", "Commission visit needs a JOURNEYMAN+ assignee")
    visit["status"] = "CONFIRMED"
    db.touch(visit)
    # bubble-up: INSTALL while project PROVISIONING -> SCHEDULED
    project = db.projects[project_id]
    if visit["visit_kind"] == "INSTALL" and project["status"] == "PROVISIONING":
        project["status"] = "SCHEDULED"
        db.touch(project)
    return success(h.public(visit))


@bp.post("/projects/<project_id>/visits/<visit_id>/start")
def start_visit(project_id, visit_id):
    _, role = authenticate()
    authorize(role, {"LowVoltageTech"})
    visit = _visit_in_project(project_id, visit_id)
    if visit["status"] != "CONFIRMED":
        raise err("ERR_INVALID_STATE", "Only a CONFIRMED visit may be started")
    if clock.now() < _wstart(visit):
        raise err("ERR_VISIT_NOT_DUE", "Logical clock is before window_start")
    visit["status"] = "IN_PROGRESS"
    db.touch(visit)
    project = db.projects[project_id]
    if visit["visit_kind"] == "INSTALL" and project["status"] == "SCHEDULED":
        project["status"] = "INSTALLING"
        db.touch(project)
    return success(h.public(visit))


@bp.post("/projects/<project_id>/visits/<visit_id>/complete")
def complete_visit(project_id, visit_id):
    _, role = authenticate()
    authorize(role, {"LowVoltageTech"})
    visit = _visit_in_project(project_id, visit_id)
    if visit["status"] != "IN_PROGRESS":
        raise err("ERR_INVALID_STATE", "Only an IN_PROGRESS visit may be completed")
    visit["status"] = "COMPLETED"
    db.touch(visit)
    domain.release_visit_assignments(visit)
    project = db.projects[project_id]
    if visit["visit_kind"] == "COMMISSION":
        domain.try_commission(project)
    return success(h.public(visit))


@bp.post("/projects/<project_id>/visits/<visit_id>/cancel")
def cancel_visit(project_id, visit_id):
    _, role = authenticate()
    authorize(role, {"ProjectManager"})
    visit = _visit_in_project(project_id, visit_id)
    if visit["status"] not in ("PLANNED", "CONFIRMED"):
        raise err("ERR_INVALID_STATE", "Only a PLANNED or CONFIRMED visit may be cancelled")
    visit["status"] = "CANCELLED"
    db.touch(visit)
    domain.release_visit_assignments(visit)
    return success(h.public(visit))


@bp.post("/projects/<project_id>/visits/<visit_id>/no-show")
def no_show_visit(project_id, visit_id):
    _, role = authenticate()
    authorize(role, {"ProjectManager"})
    visit = _visit_in_project(project_id, visit_id)
    if visit["status"] != "CONFIRMED":
        raise err("ERR_INVALID_STATE", "Only a CONFIRMED visit may be marked NO_SHOW")
    if clock.now() < _wend(visit):
        raise err("ERR_VISIT_NOT_DUE", "Logical clock is before window_end")
    visit["status"] = "NO_SHOW"
    db.touch(visit)
    domain.release_visit_assignments(visit)
    return success(h.public(visit))
