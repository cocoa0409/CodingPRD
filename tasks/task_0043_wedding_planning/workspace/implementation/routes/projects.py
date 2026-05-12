"""WeddingProject routes (CRUD, lifecycle, cancel, budget reallocate)."""
from flask import Blueprint, request, g

import db
from errors import (
    raise_error,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_PROJECT_NOT_IN_DRAFT,
    ERR_PROJECT_NOT_IN_PLANNING,
    ERR_PROJECT_NOT_IN_EXECUTION,
    ERR_PROJECT_NOT_IN_SETTLEMENT,
    ERR_NO_MILESTONES,
    ERR_MILESTONE_PERCENTAGES_INVALID,
    ERR_REQUIRED_CATEGORY_UNCOVERED,
    ERR_BUDGET_OVERCOMMITTED,
    ERR_OPEN_CONTRACTS_REMAIN,
    ERR_CEREMONY_NOT_ELAPSED,
    ERR_UNFINALIZED_SETTLEMENTS,
    ERR_AUDITOR_REQUIRED,
    ERR_MILESTONE_NOT_FOUND,
)
from middleware import (
    require_roles,
    check_planner_owns_project,
)
from response import success, list_response, parse_pagination
from services.lookup import (
    get_project,
    get_template,
    assert_project_not_terminal,
)
from services.budget import recompute_project_ledger, settlement_for_contract
from services.audit import append_audit


bp = Blueprint("projects", __name__)


def _milestone_percent_sum(project_id: str) -> float:
    return sum(
        float(m["percent_of_budget"])
        for m in db.milestones.values()
        if m["project_id"] == project_id
    )


def _project_view(p: dict) -> dict:
    return dict(p)


@bp.post("/wedding-projects")
def create_project():
    require_roles("Planner")
    body = request.get_json(silent=True) or {}
    couple_name = body.get("couple_name")
    ceremony_date = body.get("ceremony_date")
    style = body.get("style")
    scale = body.get("scale")
    planner_user_id = body.get("planner_user_id")
    auditor_user_id = body.get("auditor_user_id")
    total_budget_cents = body.get("total_budget_cents")
    template_id = body.get("template_id")

    # Segregation: auditor != planner at creation
    if planner_user_id is not None and auditor_user_id is not None and planner_user_id == auditor_user_id:
        raise_error(ERR_SEGREGATION_OF_DUTIES,
                    "auditor_user_id must differ from planner_user_id")

    template = None
    if template_id:
        template = get_template(template_id)

    project = {
        "couple_name": couple_name,
        "ceremony_date": int(ceremony_date) if ceremony_date is not None else None,
        "style": style,
        "scale": scale,
        "planner_user_id": planner_user_id,
        "auditor_user_id": auditor_user_id,
        "template_id": template_id,
        "status": "DRAFT",
        "total_budget_cents": int(total_budget_cents) if total_budget_cents is not None else 0,
        "provisional_committed_cents": 0,
        "finalized_settled_cents": 0,
        "budget_balance_cents": int(total_budget_cents) if total_budget_cents is not None else 0,
        "rehearsal_version": 0,
    }
    db.add_common_create(project)
    db.projects[project["id"]] = project

    if template:
        ceremony = project["ceremony_date"] or 0
        for ms in template.get("default_milestones", []) or []:
            offset_days = int(ms.get("offset_days_from_ceremony", 0))
            due_at = ceremony + offset_days * 86400
            milestone = {
                "project_id": project["id"],
                "label": ms.get("label"),
                "due_at": due_at,
                "percent_of_budget": float(ms.get("percent_of_budget", 0)),
                "status": "PENDING",
            }
            db.add_common_create(milestone)
            db.milestones[milestone["id"]] = milestone

    return success(_project_view(project), status=201)


@bp.get("/wedding-projects")
def list_projects():
    require_roles("Planner", "Auditor", "Couple")
    limit, offset = parse_pagination(request.args)
    status_q = request.args.get("status")
    items = list(db.projects.values())
    if status_q:
        items = [p for p in items if p["status"] == status_q]
    items.sort(key=lambda p: p["created_at"])
    return list_response(items, limit, offset)


@bp.get("/wedding-projects/<project_id>")
def get_project_route(project_id):
    require_roles("Planner", "Auditor", "Couple", "VendorRep")
    p = get_project(project_id)
    if g.user_role == "Planner":
        check_planner_owns_project(p)
    return success(_project_view(p))


@bp.post("/wedding-projects/<project_id>/activate")
def activate_project(project_id):
    require_roles("Planner")
    p = get_project(project_id)
    check_planner_owns_project(p)
    assert_project_not_terminal(p)
    if p["status"] != "DRAFT":
        raise_error(ERR_PROJECT_NOT_IN_DRAFT, "Project must be DRAFT to activate")
    project_milestones = [m for m in db.milestones.values() if m["project_id"] == project_id]
    if not project_milestones:
        raise_error(ERR_NO_MILESTONES, "At least one milestone is required")
    psum = round(sum(float(m["percent_of_budget"]) for m in project_milestones), 6)
    if psum != 100.0:
        raise_error(ERR_MILESTONE_PERCENTAGES_INVALID,
                    f"Milestone percentages sum to {psum}, must be 100.0")
    p["status"] = "PLANNING"
    db.bump(p)
    return success(_project_view(p))


@bp.post("/wedding-projects/<project_id>/start-execution")
def start_execution(project_id):
    require_roles("Planner")
    p = get_project(project_id)
    check_planner_owns_project(p)
    assert_project_not_terminal(p)
    if p["status"] != "PLANNING":
        raise_error(ERR_PROJECT_NOT_IN_PLANNING, "Project must be PLANNING to start execution")
    # Required category coverage: VENUE and CATERING each have at least one ACCEPTED contract
    required = {"VENUE", "CATERING"}
    contracts = [c for c in db.contracts.values() if c["project_id"] == project_id]
    accepted_categories = set()
    for c in contracts:
        if c["contract_status"] != "ACCEPTED":
            continue
        v = db.vendors.get(c["vendor_id"])
        if v:
            accepted_categories.add(v["category"])
    if not required.issubset(accepted_categories):
        raise_error(ERR_REQUIRED_CATEGORY_UNCOVERED,
                    "VENUE and CATERING must each have at least one ACCEPTED Contract")
    if int(p["budget_balance_cents"]) < 0:
        raise_error(ERR_BUDGET_OVERCOMMITTED, "Budget balance is negative")
    p["status"] = "EXECUTION"
    db.bump(p)
    return success(_project_view(p))


@bp.post("/wedding-projects/<project_id>/enter-settlement")
def enter_settlement(project_id):
    require_roles("Planner")
    p = get_project(project_id)
    check_planner_owns_project(p)
    assert_project_not_terminal(p)
    if p["status"] != "EXECUTION":
        raise_error(ERR_PROJECT_NOT_IN_EXECUTION, "Project must be EXECUTION")
    contracts = [c for c in db.contracts.values() if c["project_id"] == project_id]
    for c in contracts:
        if c["contract_status"] not in ("ACCEPTED", "TERMINATED"):
            raise_error(ERR_OPEN_CONTRACTS_REMAIN,
                        "All contracts must be ACCEPTED or TERMINATED")
    if db.now_clock() <= int(p["ceremony_date"]):
        raise_error(ERR_CEREMONY_NOT_ELAPSED, "Ceremony date has not elapsed")
    p["status"] = "SETTLEMENT"
    db.bump(p)
    return success(_project_view(p))


@bp.post("/wedding-projects/<project_id>/close")
def close_project(project_id):
    require_roles("Auditor")
    p = get_project(project_id)
    if p["status"] != "SETTLEMENT":
        # If terminal, still report not-in-settlement (project_terminal not used here per priority)
        raise_error(ERR_PROJECT_NOT_IN_SETTLEMENT, "Project must be SETTLEMENT to close")
    # Auditor identity checks
    if g.user_id != p.get("auditor_user_id"):
        raise_error(ERR_AUDITOR_REQUIRED, "Auditor identity does not match")
    if p.get("auditor_user_id") == p.get("planner_user_id"):
        raise_error(ERR_SEGREGATION_OF_DUTIES, "Auditor must differ from Planner")
    contracts = [c for c in db.contracts.values() if c["project_id"] == project_id]
    for c in contracts:
        if c["contract_status"] == "TERMINATED":
            continue
        s = settlement_for_contract(c["id"])
        if s is None or s["status"] != "FINALIZED":
            raise_error(ERR_UNFINALIZED_SETTLEMENTS,
                        "All non-terminated contracts must have FINALIZED settlements")
    p["status"] = "CLOSED"
    db.bump(p)
    append_audit(
        project_id=project_id,
        subject_type="BUDGET",
        subject_id=project_id,
        event_kind="SETTLEMENT_FINALIZED",
        payload={
            "total_budget_cents": p["total_budget_cents"],
            "provisional_committed_cents": p["provisional_committed_cents"],
            "finalized_settled_cents": p["finalized_settled_cents"],
            "budget_balance_cents": p["budget_balance_cents"],
        },
    )
    return success(_project_view(p))


@bp.post("/wedding-projects/<project_id>/cancel")
def cancel_project(project_id):
    require_roles("Planner")
    p = get_project(project_id)
    check_planner_owns_project(p)
    if p["status"] == "CLOSED":
        # PRD §3.8 race carve-out: when a planner's cancel races an
        # auditor's close on a SETTLEMENT project and loses, the loser
        # sees ERR_PROJECT_NOT_IN_SETTLEMENT because the project's
        # status has already moved past SETTLEMENT.
        raise_error(ERR_PROJECT_NOT_IN_SETTLEMENT,
                    "Project status has moved past SETTLEMENT")
    if p["status"] == "CANCELLED":
        raise_error(ERR_PROJECT_NOT_IN_DRAFT, "Project is already cancelled")
    prior_status = p["status"]
    if prior_status in ("PLANNING", "EXECUTION"):
        # Cascade: terminate every Contract whose contract_status in {DRAFT, NEGOTIATING, SIGNED, ACCEPTED}
        from routes.contracts import _terminate_contract_cascade
        contracts = [c for c in db.contracts.values() if c["project_id"] == project_id]
        for c in contracts:
            if c["contract_status"] in ("DRAFT", "NEGOTIATING", "SIGNED", "ACCEPTED"):
                _terminate_contract_cascade(p, c)
    p["status"] = "CANCELLED"
    db.bump(p)
    recompute_project_ledger(p)
    return success(_project_view(p))


@bp.post("/wedding-projects/<project_id>/budget/reallocate")
def reallocate_budget(project_id):
    require_roles("Planner")
    p = get_project(project_id)
    check_planner_owns_project(p)
    assert_project_not_terminal(p)
    body = request.get_json(silent=True) or {}
    allocations = body.get("allocations")
    if not isinstance(allocations, list) or not allocations:
        raise_error(ERR_MILESTONE_PERCENTAGES_INVALID,
                    "allocations must be a non-empty list")
    # Validate each allocation entry
    new_percents = {}
    for entry in allocations:
        mid = entry.get("milestone_id")
        pct = entry.get("percent_of_budget")
        if mid is None or pct is None:
            raise_error(ERR_MILESTONE_PERCENTAGES_INVALID,
                        "Each allocation requires milestone_id and percent_of_budget")
        m = db.milestones.get(mid)
        if not m or m["project_id"] != project_id:
            raise_error(ERR_MILESTONE_NOT_FOUND, "Milestone not found in project")
        new_percents[mid] = float(pct)
    # Must cover every milestone on the project
    project_milestones = [m for m in db.milestones.values() if m["project_id"] == project_id]
    for m in project_milestones:
        if m["id"] not in new_percents:
            raise_error(ERR_MILESTONE_PERCENTAGES_INVALID,
                        "Reallocation must cover every milestone")
    psum = round(sum(new_percents.values()), 6)
    if psum != 100.0:
        raise_error(ERR_MILESTONE_PERCENTAGES_INVALID,
                    f"New percentages sum to {psum}, must be 100.0")
    # Budget balance must remain >= 0 (no change to total/provisional/finalized; reallocation is a no-op on balance)
    if int(p["budget_balance_cents"]) < 0:
        raise_error(ERR_BUDGET_OVERCOMMITTED, "Budget balance would be negative")
    # Capture before snapshot
    before = {m["id"]: float(m["percent_of_budget"]) for m in project_milestones}
    for m in project_milestones:
        new_pct = new_percents[m["id"]]
        if float(m["percent_of_budget"]) != new_pct:
            m["percent_of_budget"] = new_pct
            db.bump(m)
    after = {m["id"]: float(m["percent_of_budget"]) for m in project_milestones}
    append_audit(
        project_id=project_id,
        subject_type="BUDGET",
        subject_id=project_id,
        event_kind="BUDGET_REALLOCATED",
        payload={"before": before, "after": after},
    )
    # Return updated milestones list, sorted by created_at
    project_milestones.sort(key=lambda m: m["created_at"])
    return success(project_milestones, response_type="array")
