from flask import Blueprint, request

from db import new_common, pub, store, touch
from errors import ApiError, invalid_request, invalid_state, not_found
from middleware import require_roles
from response import ok, ok_list
from util import as_int, as_str, body_json, paginate, req_field

bp = Blueprint("projects", __name__)
READERS = ("FleetAdmin", "ProjectManager", "Mechanic", "Dispatcher")


def get_project_or_404(pid):
    p = store.projects.get(pid)
    if p is None:
        raise not_found("Project")
    return p


@bp.post("/fleet/projects")
@require_roles("FleetAdmin")
def create_project():
    body = body_json()
    code = as_str(req_field(body, "project_code"), "project_code")
    name = as_str(req_field(body, "name"), "name", allow_empty=True)
    budget = as_int(req_field(body, "equipment_budget_cents"), "equipment_budget_cents", minimum=0)
    if any(p["project_code"] == code for p in store.projects.values()):
        raise invalid_request("project_code must be unique")
    p = new_common()
    p.update({
        "project_code": code,
        "name": name,
        "status": "OPEN",
        "equipment_budget_cents": budget,
        "billed_total_cents": 0,
        "active_assignment_count": 0,
    })
    store.projects[p["id"]] = p
    return ok(pub(p), "object", 201)


@bp.get("/fleet/projects/<pid>")
@require_roles(*READERS)
def get_project(pid):
    return ok(pub(get_project_or_404(pid)), "object", 200)


@bp.get("/fleet/projects")
@require_roles(*READERS)
def list_projects():
    rows = list(store.projects.values())
    st = request.args.get("status")
    if st is not None:
        rows = [p for p in rows if p["status"] == st]
    items, meta = paginate(rows)
    return ok_list([pub(p) for p in items], meta)


@bp.post("/fleet/projects/<pid>/suspend")
@require_roles("FleetAdmin")
def suspend_project(pid):
    p = get_project_or_404(pid)
    if p["status"] != "OPEN":
        raise invalid_state("Only an OPEN project can be suspended")
    p["status"] = "SUSPENDED"
    touch(p)
    return ok(pub(p), "object", 200)


@bp.post("/fleet/projects/<pid>/resume")
@require_roles("FleetAdmin")
def resume_project(pid):
    p = get_project_or_404(pid)
    if p["status"] != "SUSPENDED":
        raise invalid_state("Only a SUSPENDED project can be resumed")
    p["status"] = "OPEN"
    touch(p)
    return ok(pub(p), "object", 200)


@bp.post("/fleet/projects/<pid>/close")
@require_roles("FleetAdmin")
def close_project(pid):
    p = get_project_or_404(pid)
    if p["status"] not in ("OPEN", "SUSPENDED"):
        raise invalid_state("Only an OPEN or SUSPENDED project can be closed")
    if p["active_assignment_count"] != 0:
        raise invalid_state("Project cannot be closed while it has active assignments")
    p["status"] = "CLOSED"
    touch(p)
    return ok(pub(p), "object", 200)


@bp.get("/fleet/projects/<pid>/assignments")
@require_roles(*READERS)
def project_assignments(pid):
    p = get_project_or_404(pid)
    rows = [a for a in store.assignments.values() if a["project_id"] == p["id"]]
    st = request.args.get("status")
    if st is not None:
        rows = [a for a in rows if a["status"] == st]
    items, meta = paginate(rows)
    return ok_list([pub(a) for a in items], meta)


@bp.get("/fleet/projects/<pid>/damage-reports")
@require_roles(*READERS)
def project_damage_reports(pid):
    p = get_project_or_404(pid)
    rows = [d for d in store.damage_reports.values() if d["project_id"] == p["id"]]
    st = request.args.get("status")
    if st is not None:
        rows = [d for d in rows if d["status"] == st]
    items, meta = paginate(rows)
    return ok_list([pub(d) for d in items], meta)


@bp.get("/fleet/projects/<pid>/charges")
@require_roles("FleetAdmin", "ProjectManager")
def project_charges(pid):
    p = get_project_or_404(pid)
    rows = [c for c in store.charges.values() if c["project_id"] == p["id"]]
    items, meta = paginate(rows)
    return ok_list([pub(c) for c in items], meta)


@bp.get("/fleet/projects/<pid>/transport-jobs")
@require_roles(*READERS)
def project_transport_jobs(pid):
    p = get_project_or_404(pid)
    direction = request.args.get("direction")
    if direction in ("origin", "from"):
        rows = [t for t in store.transport_jobs.values() if t["from_project_id"] == p["id"]]
    elif direction in ("destination", "to"):
        rows = [t for t in store.transport_jobs.values() if t["to_project_id"] == p["id"]]
    elif direction is None:
        rows = [t for t in store.transport_jobs.values()
                if t["from_project_id"] == p["id"] or t["to_project_id"] == p["id"]]
    else:
        raise invalid_request("direction must be 'origin' or 'destination'")
    st = request.args.get("status")
    if st is not None:
        rows = [t for t in rows if t["status"] == st]
    items, meta = paginate(rows)
    return ok_list([pub(t) for t in items], meta)


@bp.get("/fleet/projects/<pid>/mechanics")
@require_roles(*READERS)
def project_mechanics(pid):
    p = get_project_or_404(pid)
    rows = [m for m in store.mechanics.values() if m["home_project_id"] == p["id"]]
    items, meta = paginate(rows)
    return ok_list([pub(m) for m in items], meta)
