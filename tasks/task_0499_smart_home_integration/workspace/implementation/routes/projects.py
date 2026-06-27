"""Projects and project lifecycle (PRD §3.1)."""
from flask import Blueprint, request

import db
import helpers as h
from errors import err
from middleware import authenticate, authorize
from response import success, paginated
from services import domain

bp = Blueprint("projects", __name__)

READ_ROLES = {"PlatformAdmin", "SystemsDesigner", "ProjectManager", "SupportEngineer", "LowVoltageTech", "Client"}
LIST_ROLES = {"PlatformAdmin", "SystemsDesigner", "ProjectManager", "SupportEngineer", "Client"}


@bp.post("/projects")
def create_project():
    _, role = authenticate()
    authorize(role, {"ProjectManager", "SystemsDesigner"})
    body = h.get_body()
    client_id = h.require_str(body, "client_id")
    site_address = h.require_str(body, "site_address")
    region_code = h.require_enum(body, "region_code", h.REGION_CODES)
    # FK referential integrity (priority 6): client must exist
    if client_id not in db.clients:
        raise err("ERR_REFERENTIAL_INTEGRITY", "client_id does not reference an existing client")
    entity = {
        "client_id": client_id,
        "site_address": site_address,
        "region_code": region_code,
        "status": "DRAFT",
        "accepted_proposal_id": None,
        "provisioned_device_count": 0,
        "open_change_order_count": 0,
        "contract_balance_cents": 0,
    }
    db.stamp_create(entity)
    db.projects[entity["id"]] = entity
    return success(h.public(entity), status=201)


@bp.get("/projects/<project_id>")
def get_project(project_id):
    _, role = authenticate()
    authorize(role, READ_ROLES)
    entity = h.get_or_404(db.projects, project_id)
    return success(h.public(entity))


@bp.get("/projects")
def list_projects():
    _, role = authenticate()
    authorize(role, LIST_ROLES)
    limit, offset = h.parse_pagination()
    client_id = request.args.get("client_id")
    accepted_proposal_id = request.args.get("accepted_proposal_id")
    status = request.args.get("status")
    items = list(db.projects.values())
    if client_id is not None:
        items = [p for p in items if p["client_id"] == client_id]
    if accepted_proposal_id is not None:
        items = [p for p in items if p["accepted_proposal_id"] == accepted_proposal_id]
    if status is not None:
        items = [p for p in items if p["status"] == status]
    items = h.sort_by_creation(items)
    page, total = h.paginate(items, limit, offset)
    return paginated([h.public(p) for p in page], limit, offset, total)


@bp.post("/projects/<project_id>/start-provisioning")
def start_provisioning(project_id):
    _, role = authenticate()
    authorize(role, {"ProjectManager"})
    project = h.get_or_404(db.projects, project_id)
    # state precondition (priority 7): ACCEPTED -> PROVISIONING
    if project["status"] != "ACCEPTED":
        raise err("ERR_INVALID_STATE", "Project is not in ACCEPTED state")
    if not project.get("accepted_proposal_id"):
        raise err("ERR_INVALID_STATE", "No accepted proposal pinned")
    if domain.rack_for_project(project_id) is None:
        raise err("ERR_RACK_REQUIRED", "A rack must exist before provisioning")
    project["status"] = "PROVISIONING"
    db.touch(project)
    return success(h.public(project))


@bp.post("/projects/<project_id>/activate")
def activate_project(project_id):
    _, role = authenticate()
    authorize(role, {"ProjectManager"})
    project = h.get_or_404(db.projects, project_id)
    if project["status"] != "COMMISSIONED":
        raise err("ERR_INVALID_STATE", "Project is not in COMMISSIONED state")
    # fiscal gates (priority 14)
    contract = domain.active_contract_for_project(project_id)
    if contract is None or contract["status"] != "ACTIVE":
        raise err("ERR_CONTRACT_NOT_ACTIVE", "An ACTIVE contract is required")
    if project["open_change_order_count"] != 0:
        raise err("ERR_OPEN_CHANGE_ORDERS", "Open change orders must be resolved")
    project["status"] = "ACTIVE"
    db.touch(project)
    return success(h.public(project))


@bp.post("/projects/<project_id>/cancel")
def cancel_project(project_id):
    _, role = authenticate()
    authorize(role, {"ProjectManager"})
    project = h.get_or_404(db.projects, project_id)
    status = project["status"]
    if status not in ("DRAFT", "ACCEPTED", "PROVISIONING", "SCHEDULED"):
        raise err("ERR_INVALID_STATE", "Project cannot be cancelled from its current state")

    if status == "DRAFT":
        # DRAFT/SENT proposals -> SUPERSEDED
        for p in db.proposals.values():
            if p["project_id"] == project_id and p["status"] in ("DRAFT", "SENT"):
                p["status"] = "SUPERSEDED"
                db.touch(p)
    else:
        # cascade visits -> CANCELLED (releasing assignments)
        for v in db.visits.values():
            if v["project_id"] == project_id and v["status"] in ("PLANNED", "CONFIRMED", "IN_PROGRESS"):
                v["status"] = "CANCELLED"
                db.touch(v)
                domain.release_visit_assignments(v)
        # cascade devices -> RETIRED (releasing RU and mgmt_ip)
        for d in domain.devices_for_project(project_id):
            if d["status"] != "RETIRED":
                domain.retire_device(d)

    project["status"] = "CANCELLED"
    db.touch(project)
    domain.recompute_project_counters(project)
    return success(h.public(project))
