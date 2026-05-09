"""Project entity service — CRUD and lifecycle transitions."""

from decimal import Decimal

from clock import clock
from common import (
    money_to_json,
    require_field,
    round_money,
    sort_by_created_at,
    stamp_create,
    stamp_update,
    to_decimal,
)
from db import db
from errors import (
    ERR_INSUFFICIENT_REVIEWS,
    ERR_INVALID_DATE_RANGE,
    ERR_INVALID_INPUT,
    ERR_INVALID_STATE,
    ERR_NOT_PROJECT_OWNER,
    ERR_OPEN_REIMBURSEMENTS_EXIST,
    ERR_PROJECT_CODE_COLLISION,
    ERR_PROJECT_NOT_FOUND,
    ERR_PROJECT_NOT_YET_STARTED,
    ERR_PROPOSAL_TOO_SHORT,
    ERR_REVIEW_CONSENSUS_NOT_MET,
    ERR_START_IN_PAST,
    raise_error,
)
from services.audit_log import append_log


SOURCE_ABBR = {
    "NATIONAL": "NTL",
    "PROVINCIAL": "PRV",
    "ENTERPRISE": "ENT",
    "INTERNAL": "INT",
}
VALID_FUNDING_SOURCES = set(SOURCE_ABBR.keys())


def get_project_or_404(project_id):
    p = db.projects.get(project_id)
    if p is None:
        raise_error(ERR_PROJECT_NOT_FOUND, f"project {project_id} not found")
    return p


def serialize_project(p):
    return {
        "id": p["id"],
        "title": p["title"],
        "principal_investigator_id": p["principal_investigator_id"],
        "department_id": p["department_id"],
        "funding_source": p["funding_source"],
        "proposal_text": p["proposal_text"],
        "requested_amount": money_to_json(p["requested_amount"]),
        "project_code": p.get("project_code"),
        "planned_start_date": p["planned_start_date"],
        "planned_end_date": p["planned_end_date"],
        "total_budget": money_to_json(p.get("total_budget", Decimal("0"))),
        "total_reimbursed": money_to_json(p.get("total_reimbursed", Decimal("0"))),
        "indirect_cost_amount": money_to_json(p["indirect_cost_amount"]) if p.get("indirect_cost_amount") is not None else None,
        "status": p["status"],
        "closing_findings_count": p.get("closing_findings_count", 0),
        "floor_area_sqm": p.get("floor_area_sqm"),
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def create_project(body, actor_id):
    title = require_field(body, "title", str)
    if not (1 <= len(title) <= 200):
        raise_error(ERR_INVALID_INPUT, "title length out of range")
    pi_id = require_field(body, "principal_investigator_id", str)
    if pi_id != actor_id:
        # principal_investigator_id must equal X-User-ID at creation
        raise_error(ERR_NOT_PROJECT_OWNER, "principal_investigator_id must equal X-User-ID")
    department_id = require_field(body, "department_id", str)
    funding_source = require_field(body, "funding_source", str)
    if funding_source not in VALID_FUNDING_SOURCES:
        raise_error(ERR_INVALID_INPUT, "invalid funding_source")
    proposal_text = require_field(body, "proposal_text", str)
    requested_amount = round_money(to_decimal(require_field(body, "requested_amount")))
    if requested_amount < 0:
        raise_error(ERR_INVALID_INPUT, "requested_amount must be non-negative")
    planned_start_date = require_field(body, "planned_start_date", int)
    planned_end_date = require_field(body, "planned_end_date", int)
    floor_area_sqm = body.get("floor_area_sqm")
    if floor_area_sqm is not None and not isinstance(floor_area_sqm, (int, float)):
        raise_error(ERR_INVALID_INPUT, "floor_area_sqm must be numeric")

    pid = db.new_id()
    project = {
        "id": pid,
        "title": title,
        "principal_investigator_id": pi_id,
        "department_id": department_id,
        "funding_source": funding_source,
        "proposal_text": proposal_text,
        "requested_amount": requested_amount,
        "project_code": None,
        "planned_start_date": planned_start_date,
        "planned_end_date": planned_end_date,
        "total_budget": Decimal("0.00"),
        "total_reimbursed": Decimal("0.00"),
        "indirect_cost_amount": None,
        "status": "DRAFT",
        "closing_findings_count": 0,
        "floor_area_sqm": floor_area_sqm,
    }
    stamp_create(project)
    db.projects[pid] = project
    return project


def list_projects(limit, offset, status=None, funding_source=None):
    items = list(db.projects.values())
    if status:
        items = [p for p in items if p["status"] == status]
    if funding_source:
        items = [p for p in items if p["funding_source"] == funding_source]
    items = sort_by_created_at(items)
    return items


def submit_project(project_id, actor_id):
    p = get_project_or_404(project_id)
    if p["principal_investigator_id"] != actor_id:
        raise_error(ERR_NOT_PROJECT_OWNER, "only PI can submit")
    if p["status"] != "DRAFT":
        raise_error(ERR_INVALID_STATE, f"cannot submit from status {p['status']}")
    # input-shape preconditions
    if len(p["proposal_text"]) < 200:
        raise_error(ERR_PROPOSAL_TOO_SHORT, "proposal_text must be >= 200 chars")
    if p["planned_end_date"] <= p["planned_start_date"]:
        raise_error(ERR_INVALID_DATE_RANGE, "planned_end_date must be > planned_start_date")
    now = clock.now_epoch()
    if p["planned_start_date"] < now:
        raise_error(ERR_START_IN_PAST, "planned_start_date must be >= now()")
    p["status"] = "UNDER_REVIEW"
    stamp_update(p)
    return p


def _next_project_code(funding_source):
    year = clock.current_year()
    key = (year, funding_source)
    seq = db.project_code_counter.get(key, 0) + 1
    if seq > 9999:
        raise_error(ERR_PROJECT_CODE_COLLISION, "sequence exhausted for (year, source)")
    db.project_code_counter[key] = seq
    return f"{year}-{SOURCE_ABBR[funding_source]}-{seq:04d}"


def approve_project(project_id, actor_id, actor_role):
    p = get_project_or_404(project_id)
    if p["status"] != "UNDER_REVIEW":
        raise_error(ERR_INVALID_STATE, f"project not UNDER_REVIEW (got {p['status']})")

    reviews = [r for r in db.peer_reviews.values() if r["project_id"] == project_id]
    if len(reviews) < 3:
        raise_error(ERR_INSUFFICIENT_REVIEWS, "project requires >= 3 peer reviews")
    approve_count = sum(1 for r in reviews if r["recommendation"] == "APPROVE")
    reject_count = sum(1 for r in reviews if r["recommendation"] == "REJECT")
    if not (approve_count > reject_count):
        raise_error(ERR_REVIEW_CONSENSUS_NOT_MET, "APPROVE must strictly outnumber REJECT")

    # Mint project_code
    p["project_code"] = _next_project_code(p["funding_source"])
    p["status"] = "APPROVED"
    stamp_update(p)

    # Approve all BudgetItems
    items = [bi for bi in db.budget_items.values() if bi["project_id"] == project_id]
    total = Decimal("0.00")
    for bi in items:
        before = {"status": bi["status"], "approved_amount": money_to_json(bi.get("approved_amount"))}
        bi["status"] = "APPROVED"
        bi["approved_amount"] = round_money(bi["requested_amount"])
        bi["remaining_amount"] = bi["approved_amount"] - bi["spent_amount"]
        stamp_update(bi)
        after = {"status": bi["status"], "approved_amount": money_to_json(bi["approved_amount"])}
        total += bi["approved_amount"]
        append_log("BUDGET_ITEM", bi["id"], "APPROVE", actor_role, actor_id, before, after)

    p["total_budget"] = round_money(total)
    return p


def reject_project(project_id, actor_id, actor_role):
    p = get_project_or_404(project_id)
    if p["status"] != "UNDER_REVIEW":
        raise_error(ERR_INVALID_STATE, f"project not UNDER_REVIEW (got {p['status']})")
    reviews = [r for r in db.peer_reviews.values() if r["project_id"] == project_id]
    if len(reviews) < 3:
        raise_error(ERR_INSUFFICIENT_REVIEWS, "project requires >= 3 peer reviews")
    p["status"] = "REJECTED"
    stamp_update(p)
    return p


def activate_project(project_id):
    p = get_project_or_404(project_id)
    if p["status"] != "APPROVED":
        raise_error(ERR_INVALID_STATE, f"project not APPROVED (got {p['status']})")
    now = clock.now_epoch()
    if now < p["planned_start_date"]:
        raise_error(ERR_PROJECT_NOT_YET_STARTED, "now() < planned_start_date")
    p["status"] = "ACTIVE"
    stamp_update(p)
    return p


def begin_closing(project_id, actor_id):
    p = get_project_or_404(project_id)
    if p["principal_investigator_id"] != actor_id:
        raise_error(ERR_NOT_PROJECT_OWNER, "only PI can begin closing")
    if p["status"] != "ACTIVE":
        raise_error(ERR_INVALID_STATE, f"project not ACTIVE (got {p['status']})")
    # Open reimbursement check
    open_states = {"SUBMITTED", "UNDER_REVIEW"}
    for r in db.reimbursements.values():
        if r["project_id"] == project_id and r["status"] in open_states:
            raise_error(ERR_OPEN_REIMBURSEMENTS_EXIST, "open reimbursements remain")
    p["status"] = "CLOSING"
    stamp_update(p)
    # Lock all BudgetItems
    for bi in db.budget_items.values():
        if bi["project_id"] == project_id:
            bi["status"] = "LOCKED"
            stamp_update(bi)
    return p
