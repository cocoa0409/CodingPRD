"""Change orders (PRD §3.3)."""
import clock
from flask import Blueprint, request

import db
import helpers as h
from errors import err
from middleware import authenticate, authorize
from response import success, paginated
from services import calc, domain

bp = Blueprint("change_orders", __name__)

READ_ROLES = {"PlatformAdmin", "ProjectManager", "SystemsDesigner", "Client"}
APPROVE_PROJECT_STATES = {"ACCEPTED", "PROVISIONING", "SCHEDULED", "INSTALLING", "COMMISSIONED"}


def _co_in_project(project_id, co_id):
    h.get_or_404(db.projects, project_id)
    co = db.change_orders.get(co_id)
    if co is None or co["project_id"] != project_id:
        raise err("ERR_NOT_FOUND", "Change order not found in project")
    return co


@bp.post("/projects/<project_id>/change-orders")
def submit_change_order(project_id):
    _, role = authenticate()
    authorize(role, {"ProjectManager", "SystemsDesigner"})
    project = h.get_or_404(db.projects, project_id)
    body = h.get_body()
    description = h.require_str(body, "description")
    delta_cents = h.require_int(body, "delta_cents")
    added_labor_hours = h.optional_number(body, "added_labor_hours", 0, minimum=0)
    entity = {
        "project_id": project_id,
        "description": description,
        "delta_cents": delta_cents,
        "added_labor_hours": added_labor_hours,
        "status": "SUBMITTED",
        "applied_at": None,
    }
    db.stamp_create(entity)
    db.change_orders[entity["id"]] = entity
    domain.recompute_project_counters(project)
    return success(h.public(entity), status=201)


@bp.get("/projects/<project_id>/change-orders")
def list_change_orders(project_id):
    _, role = authenticate()
    authorize(role, READ_ROLES)
    h.get_or_404(db.projects, project_id)
    limit, offset = h.parse_pagination()
    status = request.args.get("status")
    items = [c for c in db.change_orders.values() if c["project_id"] == project_id]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    items = h.sort_by_creation(items)
    page, total = h.paginate(items, limit, offset)
    return paginated([h.public(c) for c in page], limit, offset, total)


@bp.get("/projects/<project_id>/change-orders/<co_id>")
def get_change_order(project_id, co_id):
    _, role = authenticate()
    authorize(role, READ_ROLES)
    co = _co_in_project(project_id, co_id)
    return success(h.public(co))


@bp.post("/projects/<project_id>/change-orders/<co_id>/approve")
def approve_change_order(project_id, co_id):
    user_id, role = authenticate()
    authorize(role, {"Client"})
    project = h.get_or_404(db.projects, project_id)
    co = db.change_orders.get(co_id)
    if co is None or co["project_id"] != project_id:
        raise err("ERR_NOT_FOUND", "Change order not found in project")
    if project["client_id"] != user_id:
        raise err("ERR_NOT_OWNER", "Acting client does not own the project")
    if co["status"] != "SUBMITTED":
        raise err("ERR_INVALID_STATE", "Only a SUBMITTED change order may be approved")
    if project["status"] not in APPROVE_PROJECT_STATES:
        raise err("ERR_INVALID_STATE", "Project state does not permit approval")
    co["status"] = "APPROVED"
    db.touch(co)
    return success(h.public(co))


@bp.post("/projects/<project_id>/change-orders/<co_id>/reject")
def reject_change_order(project_id, co_id):
    user_id, role = authenticate()
    authorize(role, {"Client"})
    project = h.get_or_404(db.projects, project_id)
    co = db.change_orders.get(co_id)
    if co is None or co["project_id"] != project_id:
        raise err("ERR_NOT_FOUND", "Change order not found in project")
    if project["client_id"] != user_id:
        raise err("ERR_NOT_OWNER", "Acting client does not own the project")
    if co["status"] not in ("SUBMITTED", "APPROVED"):
        raise err("ERR_INVALID_STATE", "Only a SUBMITTED or APPROVED change order may be rejected")
    co["status"] = "REJECTED"
    db.touch(co)
    domain.recompute_project_counters(project)
    return success(h.public(co))


@bp.post("/projects/<project_id>/change-orders/<co_id>/apply")
def apply_change_order(project_id, co_id):
    _, role = authenticate()
    authorize(role, {"ProjectManager"})
    project = h.get_or_404(db.projects, project_id)
    co = db.change_orders.get(co_id)
    if co is None or co["project_id"] != project_id:
        raise err("ERR_NOT_FOUND", "Change order not found in project")
    body = h.get_body()
    expected_version = h.require_int(body, "expected_project_version")
    if co["status"] != "APPROVED":
        raise err("ERR_INVALID_STATE", "Only an APPROVED change order may be applied")
    if not project.get("accepted_proposal_id"):
        raise err("ERR_INVALID_STATE", "Project has no accepted proposal")
    # OCC (priority 15) last
    if expected_version != project["version"]:
        raise err("ERR_STALE_VERSION", "expected_project_version does not match current project version")

    proposal = db.proposals[project["accepted_proposal_id"]]
    # apply delta authoritatively to grand_total
    proposal["grand_total_cents"] = proposal["grand_total_cents"] + co["delta_cents"]
    # add labor hours; recompute labor_cost_cents for record-keeping only
    proposal["labor_hours_estimate"] = proposal["labor_hours_estimate"] + co["added_labor_hours"]
    client = db.clients[project["client_id"]]
    proposal["labor_cost_cents"] = calc.labor_cost_only(
        proposal["labor_hours_estimate"], client["billing_tier"], project["region_code"]
    )
    db.touch(proposal)

    co["status"] = "APPLIED"
    co["applied_at"] = db._iso(clock.now())
    db.touch(co)

    # recompute open_change_order_count + bump project version by 1
    occ = sum(
        1 for c in db.change_orders.values()
        if c["project_id"] == project_id and c["status"] in ("SUBMITTED", "APPROVED")
    )
    project["open_change_order_count"] = occ
    db.touch(project)
    return success(h.public(co))
