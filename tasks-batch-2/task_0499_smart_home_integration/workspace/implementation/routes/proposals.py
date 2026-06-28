"""Proposals, line items, and the proposal lifecycle (PRD §3.2, §3.3)."""
from flask import Blueprint, request

import db
import helpers as h
from errors import err
from middleware import authenticate, authorize
from response import success, paginated
from services import calc

bp = Blueprint("proposals", __name__)

READ_ROLES = {"PlatformAdmin", "SystemsDesigner", "ProjectManager", "Client"}


def _line_items_for(proposal_id):
    return [li for li in db.line_items.values() if li["proposal_id"] == proposal_id]


def _proposal_in_project(project_id, proposal_id):
    # left-to-right existence (priority 3): project then proposal-in-scope
    h.get_or_404(db.projects, project_id)
    proposal = db.proposals.get(proposal_id)
    if proposal is None or proposal["project_id"] != project_id:
        raise err("ERR_NOT_FOUND", "Proposal not found in project")
    return proposal


def _recompute_proposal(proposal):
    project = db.projects[proposal["project_id"]]
    client = db.clients[project["client_id"]]
    totals = calc.proposal_total(
        _line_items_for(proposal["id"]),
        client["billing_tier"],
        project["region_code"],
        proposal["labor_hours_estimate"],
    )
    proposal.update(totals)


# ---------------------------------------------------------------------------
# Create proposal (OCC on project version) — PRD §3.2, §2.8
# ---------------------------------------------------------------------------
@bp.post("/projects/<project_id>/proposals")
def create_proposal(project_id):
    _, role = authenticate()
    authorize(role, {"SystemsDesigner"})
    project = h.get_or_404(db.projects, project_id)
    body = h.get_body()
    labor_hours_estimate = h.require_number(body, "labor_hours_estimate", minimum=0)
    expected_version = h.require_int(body, "expected_project_version")
    # OCC check (priority 15) — last
    if expected_version != project["version"]:
        raise err("ERR_STALE_VERSION", "expected_project_version does not match current project version")

    # revision = highest existing + 1
    existing = [p for p in db.proposals.values() if p["project_id"] == project_id]
    max_rev = max((p["revision"] for p in existing), default=0)
    revision = max_rev + 1

    # supersede any open DRAFT/SENT proposal
    for p in existing:
        if p["status"] in ("DRAFT", "SENT"):
            p["status"] = "SUPERSEDED"
            db.touch(p)

    entity = {
        "project_id": project_id,
        "revision": revision,
        "status": "DRAFT",
        "labor_hours_estimate": labor_hours_estimate,
        "equipment_subtotal_cents": 0,
        "labor_cost_cents": 0,
        "discount_cents": 0,
        "tax_cents": 0,
        "grand_total_cents": 0,
    }
    db.stamp_create(entity)
    db.proposals[entity["id"]] = entity

    # increments Project.version by 1
    db.touch(project)
    return success(h.public(entity), status=201)


@bp.get("/projects/<project_id>/proposals")
def list_proposals(project_id):
    _, role = authenticate()
    authorize(role, READ_ROLES)
    h.get_or_404(db.projects, project_id)
    limit, offset = h.parse_pagination()
    status = request.args.get("status")
    items = [p for p in db.proposals.values() if p["project_id"] == project_id]
    if status is not None:
        items = [p for p in items if p["status"] == status]
    items = h.sort_by_creation(items)
    page, total = h.paginate(items, limit, offset)
    return paginated([h.public(p) for p in page], limit, offset, total)


@bp.get("/projects/<project_id>/proposals/<proposal_id>")
def get_proposal_nested(project_id, proposal_id):
    _, role = authenticate()
    authorize(role, READ_ROLES)
    proposal = _proposal_in_project(project_id, proposal_id)
    return success(h.public(proposal))


@bp.get("/proposals/<proposal_id>")
def get_proposal_flat(proposal_id):
    _, role = authenticate()
    authorize(role, READ_ROLES)
    proposal = h.get_or_404(db.proposals, proposal_id)
    return success(h.public(proposal))


@bp.get("/proposals/<proposal_id>/line-items")
def list_line_items_flat(proposal_id):
    _, role = authenticate()
    authorize(role, READ_ROLES)
    h.get_or_404(db.proposals, proposal_id)
    limit, offset = h.parse_pagination()
    items = h.sort_by_creation(_line_items_for(proposal_id))
    page, total = h.paginate(items, limit, offset)
    return paginated([h.public(li) for li in page], limit, offset, total)


@bp.post("/projects/<project_id>/proposals/<proposal_id>/line-items")
def add_line_item(project_id, proposal_id):
    _, role = authenticate()
    authorize(role, {"SystemsDesigner"})
    proposal = _proposal_in_project(project_id, proposal_id)
    body = h.get_body()
    sku = h.require_str(body, "sku")
    category = h.require_enum(body, "category", h.DEVICE_CATEGORIES)
    qty = h.require_int(body, "qty", minimum=1)
    unit_price_cents = h.require_int(body, "unit_price_cents", minimum=0)
    # state: only on a DRAFT proposal (frozen at SENT) (priority 7)
    if proposal["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Line items may only be added to a DRAFT proposal")
    entity = {
        "proposal_id": proposal_id,
        "sku": sku,
        "category": category,
        "qty": qty,
        "unit_price_cents": unit_price_cents,
        "removed": False,
    }
    db.stamp_create(entity)
    db.line_items[entity["id"]] = entity
    # recompute proposal totals (provisional)
    _recompute_proposal(proposal)
    db.touch(proposal)
    return success(h.public(entity), status=201)


@bp.get("/projects/<project_id>/proposals/<proposal_id>/line-items")
def list_line_items_nested(project_id, proposal_id):
    _, role = authenticate()
    authorize(role, READ_ROLES)
    _proposal_in_project(project_id, proposal_id)
    limit, offset = h.parse_pagination()
    items = h.sort_by_creation(_line_items_for(proposal_id))
    page, total = h.paginate(items, limit, offset)
    return paginated([h.public(li) for li in page], limit, offset, total)


@bp.post("/projects/<project_id>/proposals/<proposal_id>/line-items/<line_item_id>/remove")
def remove_line_item(project_id, proposal_id, line_item_id):
    _, role = authenticate()
    authorize(role, {"SystemsDesigner"})
    proposal = _proposal_in_project(project_id, proposal_id)
    li = db.line_items.get(line_item_id)
    if li is None or li["proposal_id"] != proposal_id:
        raise err("ERR_NOT_FOUND", "Line item not found in proposal")
    if proposal["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Line items may only be removed from a DRAFT proposal")
    li["removed"] = True
    db.touch(li)
    _recompute_proposal(proposal)
    db.touch(proposal)
    return success(h.public(li))


@bp.post("/projects/<project_id>/proposals/<proposal_id>/send")
def send_proposal(project_id, proposal_id):
    _, role = authenticate()
    authorize(role, {"SystemsDesigner"})
    project = h.get_or_404(db.projects, project_id)
    proposal = db.proposals.get(proposal_id)
    if proposal is None or proposal["project_id"] != project_id:
        raise err("ERR_NOT_FOUND", "Proposal not found in project")
    # state: DRAFT -> SENT (priority 7)
    if proposal["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Only a DRAFT proposal may be sent")
    # safety/business: >= 1 non-removed line item
    non_removed = [li for li in _line_items_for(proposal_id) if not li["removed"]]
    if not non_removed:
        raise err("ERR_EMPTY_PROPOSAL", "Proposal has no non-removed line items")
    # project must be DRAFT
    if project["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Project is not in DRAFT state")
    # recompute totals; freeze (status flip), move project DRAFT -> PROPOSED
    _recompute_proposal(proposal)
    proposal["status"] = "SENT"
    db.touch(proposal)
    project["status"] = "PROPOSED"
    db.touch(project)
    return success(h.public(proposal))


@bp.post("/projects/<project_id>/proposals/<proposal_id>/accept")
def accept_proposal(project_id, proposal_id):
    user_id, role = authenticate()
    authorize(role, {"Client"})
    project = h.get_or_404(db.projects, project_id)
    proposal = db.proposals.get(proposal_id)
    if proposal is None or proposal["project_id"] != project_id:
        raise err("ERR_NOT_FOUND", "Proposal not found in project")
    # ownership (priority 4)
    if project["client_id"] != user_id:
        raise err("ERR_NOT_OWNER", "Acting client does not own the project")
    # state: proposal SENT and project PROPOSED (priority 7)
    if proposal["status"] != "SENT":
        raise err("ERR_INVALID_STATE", "Only a SENT proposal may be accepted")
    if project["status"] != "PROPOSED":
        raise err("ERR_INVALID_STATE", "Project is not in PROPOSED state")
    # no other ACCEPTED proposal of this project
    for p in db.proposals.values():
        if p["project_id"] == project_id and p["status"] == "ACCEPTED":
            raise err("ERR_PROPOSAL_ALREADY_ACCEPTED", "Another proposal is already accepted")
    proposal["status"] = "ACCEPTED"
    db.touch(proposal)
    project["accepted_proposal_id"] = proposal_id
    project["status"] = "ACCEPTED"
    db.touch(project)
    return success(h.public(proposal))


@bp.post("/projects/<project_id>/proposals/<proposal_id>/reject")
def reject_proposal(project_id, proposal_id):
    user_id, role = authenticate()
    authorize(role, {"Client"})
    project = h.get_or_404(db.projects, project_id)
    proposal = db.proposals.get(proposal_id)
    if proposal is None or proposal["project_id"] != project_id:
        raise err("ERR_NOT_FOUND", "Proposal not found in project")
    if project["client_id"] != user_id:
        raise err("ERR_NOT_OWNER", "Acting client does not own the project")
    if proposal["status"] != "SENT":
        raise err("ERR_INVALID_STATE", "Only a SENT proposal may be rejected")
    if project["status"] != "PROPOSED":
        raise err("ERR_INVALID_STATE", "Project is not in PROPOSED state")
    proposal["status"] = "REJECTED"
    db.touch(proposal)
    project["status"] = "DRAFT"
    db.touch(project)
    return success(h.public(proposal))
