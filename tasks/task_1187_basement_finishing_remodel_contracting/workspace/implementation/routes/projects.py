"""Project endpoints: create, list, get, resume, cancel (PRD §3.1, §3.7)."""
from flask import Blueprint, request

from db import stores
from errors import fail
from response import ok
from serializers import ser_project
from services import (
    PROJECT_TERMINAL, resume_project, cancel_project,
)
from validation import auth, require_role, get_body, v_str, v_int
from routes.common import (
    project_or_404, require_project_owner, require_contractor_owner,
    new_entity, list_response,
)

bp = Blueprint("projects", __name__)


@bp.post("/api/projects")
def create_project():
    role, uid = auth()
    require_role(role, "Contractor")
    project = None
    body = get_body()
    # Priority 5: body reference homeowner_id must resolve.
    homeowner_id = body.get("homeowner_id")
    if isinstance(homeowner_id, str) and homeowner_id not in stores["homeowners"]:
        fail("ERR_REFERENCED_NOT_FOUND", "homeowner_id does not reference an existing homeowner")
    # Priority 25: base_contract_cents must be greater than zero.
    bcc = body.get("base_contract_cents")
    if isinstance(bcc, int) and not isinstance(bcc, bool) and bcc <= 0:
        fail("ERR_INVALID_CLAIM_AMOUNT", "base_contract_cents must be greater than zero")
    # Priority 26: request shape.
    homeowner_id = v_str(body, "homeowner_id")
    address = v_str(body, "address")
    basement_sqft = v_int(body, "basement_sqft")
    base_contract_cents = v_int(body, "base_contract_cents")
    e = new_entity({
        "homeowner_id": homeowner_id,
        # contractor_id stamped from the acting Contractor identity, never the body.
        "contractor_id": uid,
        "address": address,
        "basement_sqft": basement_sqft,
        "base_contract_cents": base_contract_cents,
        "status": "INTAKE",
        "last_resumed_at": None,
        "_last_resumed_dt": None,
        "_last_resumed_seq": None,
        "approved_design_id": None,
    })
    stores["projects"][e["id"]] = e
    return ok(ser_project(e), 201)


@bp.get("/api/projects")
def list_projects():
    auth()
    items = list(stores["projects"].values())
    for key in ("homeowner_id", "contractor_id", "status", "approved_design_id"):
        val = request.args.get(key)
        if val is not None:
            items = [p for p in items if str(p.get(key)) == val]
    return list_response(items, ser_project)


@bp.get("/api/projects/<project_id>")
def get_project(project_id):
    auth()
    return ok(ser_project(project_or_404(project_id)))


@bp.post("/api/projects/<project_id>/resume")
def resume(project_id):
    role, uid = auth()
    require_role(role, "Contractor")
    project = project_or_404(project_id)
    require_contractor_owner(project, uid)
    if project["status"] in PROJECT_TERMINAL:
        fail("ERR_ALREADY_TERMINAL", "Project is terminal and refuses further mutation")
    if project["status"] != "SUSPENDED":
        fail("ERR_INVALID_STATE", "Only a SUSPENDED project can be resumed")
    body = get_body()
    v_str(body, "remediation_note")
    resume_project(project)
    return ok(ser_project(project))


@bp.post("/api/projects/<project_id>/cancel")
def cancel(project_id):
    role, uid = auth()
    require_role(role, "Contractor", "Homeowner")
    project = project_or_404(project_id)
    require_project_owner(project, role, uid)
    if project["status"] in PROJECT_TERMINAL:
        fail("ERR_ALREADY_TERMINAL", "Project is terminal and refuses further mutation")
    body = get_body()
    v_str(body, "reason", required=False)
    cancel_project(project)
    return ok(ser_project(project))
