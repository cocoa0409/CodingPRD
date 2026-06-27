"""Service contracts and remote-support balance (PRD §3.9)."""
from flask import Blueprint

import db
import helpers as h
from errors import err
from middleware import authenticate, authorize
from response import success
from services import calc, domain

bp = Blueprint("contracts", __name__)

READ_ROLES = {"PlatformAdmin", "SupportEngineer", "ProjectManager", "Client"}


def _contract_for_project(project_id):
    """The single non-terminal-or-any contract; here we return any contract on
    the project (there is at most one active/suspended). For lifecycle ops we
    need the contract instance, resolved as the project's current contract."""
    contracts = [c for c in db.contracts.values() if c["project_id"] == project_id]
    return contracts


def _recompute_balance(contract):
    contract["balance_cents"] = calc.contract_balance(
        contract["prepaid_hours"], contract["consumed_hours"], contract["hourly_rate_cents"]
    )


@bp.post("/projects/<project_id>/contract")
def create_contract(project_id):
    _, role = authenticate()
    authorize(role, {"SupportEngineer", "ProjectManager"})
    h.get_or_404(db.projects, project_id)
    body = h.get_body()
    plan = h.require_enum(body, "plan", h.CONTRACT_PLANS)
    prepaid_hours = h.require_number(body, "prepaid_hours", minimum=0)
    hourly_rate_cents = h.require_int(body, "hourly_rate_cents", minimum=0)
    entity = {
        "project_id": project_id,
        "plan": plan,
        "prepaid_hours": prepaid_hours,
        "hourly_rate_cents": hourly_rate_cents,
        "consumed_hours": 0,
        "status": "PENDING",
        "balance_cents": 0,
    }
    db.stamp_create(entity)
    db.contracts[entity["id"]] = entity
    return success(h.public(entity), status=201)


@bp.get("/projects/<project_id>/contract")
def get_contract(project_id):
    _, role = authenticate()
    authorize(role, READ_ROLES)
    h.get_or_404(db.projects, project_id)
    items = h.sort_by_creation(_contract_for_project(project_id))
    # array of zero or one (PRD §3.9) — but multiple terminal contracts may
    # exist over a project's life; return all on the project sorted by creation.
    return success([h.public(c) for c in items])


def _resolve_active_or_recent(project_id):
    contracts = _contract_for_project(project_id)
    if not contracts:
        raise err("ERR_NOT_FOUND", "No contract on project")
    return contracts


@bp.post("/projects/<project_id>/contract/activate")
def activate_contract(project_id):
    _, role = authenticate()
    authorize(role, {"SupportEngineer"})
    project = h.get_or_404(db.projects, project_id)
    contracts = _resolve_active_or_recent(project_id)
    # Act on a PENDING contract (the transition source). If none PENDING, the
    # most recent contract drives state error.
    target = None
    for c in sorted(contracts, key=lambda x: x["_seq"], reverse=True):
        if c["status"] == "PENDING":
            target = c
            break
    if target is None:
        raise err("ERR_INVALID_STATE", "No PENDING contract to activate")
    # project must be COMMISSIONED or ACTIVE
    if project["status"] not in ("COMMISSIONED", "ACTIVE"):
        raise err("ERR_INVALID_STATE", "Project must be COMMISSIONED or ACTIVE")
    # no other ACTIVE/SUSPENDED contract on project
    for c in contracts:
        if c["id"] != target["id"] and c["status"] in ("ACTIVE", "SUSPENDED"):
            raise err("ERR_CONTRACT_ALREADY_ACTIVE", "Another contract is already active or suspended")
    target["status"] = "ACTIVE"
    _recompute_balance(target)
    db.touch(target)
    domain.recompute_project_counters(project)
    return success(h.public(target))


def _single_status_target(project_id, source_status):
    contracts = _resolve_active_or_recent(project_id)
    for c in sorted(contracts, key=lambda x: x["_seq"], reverse=True):
        if c["status"] == source_status:
            return c
    raise err("ERR_INVALID_STATE", f"No contract in {source_status} state")


@bp.post("/projects/<project_id>/contract/suspend")
def suspend_contract(project_id):
    _, role = authenticate()
    authorize(role, {"SupportEngineer"})
    project = h.get_or_404(db.projects, project_id)
    target = _single_status_target(project_id, "ACTIVE")
    target["status"] = "SUSPENDED"
    db.touch(target)
    domain.recompute_project_counters(project)
    return success(h.public(target))


@bp.post("/projects/<project_id>/contract/resume")
def resume_contract(project_id):
    _, role = authenticate()
    authorize(role, {"SupportEngineer"})
    project = h.get_or_404(db.projects, project_id)
    target = _single_status_target(project_id, "SUSPENDED")
    target["status"] = "ACTIVE"
    db.touch(target)
    domain.recompute_project_counters(project)
    return success(h.public(target))


@bp.post("/projects/<project_id>/contract/cancel")
def cancel_contract(project_id):
    _, role = authenticate()
    authorize(role, {"SupportEngineer"})
    project = h.get_or_404(db.projects, project_id)
    contracts = _resolve_active_or_recent(project_id)
    target = None
    for c in sorted(contracts, key=lambda x: x["_seq"], reverse=True):
        if c["status"] in ("ACTIVE", "SUSPENDED"):
            target = c
            break
    if target is None:
        raise err("ERR_INVALID_STATE", "No ACTIVE or SUSPENDED contract to cancel")
    # no RMA on this contract in OPENED/AUTHORIZED/SHIPPED
    for r in db.rma_tickets.values():
        if r["contract_id"] == target["id"] and r["status"] in ("OPENED", "AUTHORIZED", "SHIPPED"):
            raise err("ERR_CONTRACT_HAS_OPEN_RMA", "Contract has an open RMA")
    target["status"] = "CANCELLED"
    db.touch(target)
    project["contract_balance_cents"] = 0
    db.touch(project)
    domain.recompute_project_counters(project)
    return success(h.public(target))


@bp.post("/projects/<project_id>/contract/consume")
def consume_contract(project_id):
    _, role = authenticate()
    authorize(role, {"SupportEngineer"})
    project = h.get_or_404(db.projects, project_id)
    body = h.get_body()
    hours = h.require_number(body, "hours", minimum=0)
    # act on the project's ACTIVE contract
    target = None
    for c in sorted(_contract_for_project(project_id), key=lambda x: x["_seq"], reverse=True):
        if c["status"] == "ACTIVE":
            target = c
            break
    if target is None:
        raise err("ERR_INVALID_STATE", "No ACTIVE contract to consume against")
    target["consumed_hours"] = target["consumed_hours"] + hours
    _recompute_balance(target)
    db.touch(target)
    domain.recompute_project_counters(project)
    return success(h.public(target))
