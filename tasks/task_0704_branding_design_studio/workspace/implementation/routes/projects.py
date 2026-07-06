"""Project endpoints (PRD §3.2, §3.5, §3.9)."""
from flask import Blueprint, request

from db import db
from middleware import authenticate
from errors import (
    err, ERR_NOT_FOUND, ERR_INVALID_STATE, ERR_NO_MILESTONES,
    ERR_CLIENT_NOT_ACTIVE, ERR_MOODBOARD_NOT_APPROVED, ERR_NO_APPROVED_CONCEPT,
    ERR_DELIVERABLES_INCOMPLETE, ERR_DEPOSIT_UNPAID, ERR_OPEN_INVOICES,
)
from helpers import (
    require_role, get_json_body, require_fields, as_string, as_number,
    require_enum, require_nonneg_int, get_studio, get_or_404,
    parse_pagination, paginate, require_client_owns_project,
)
from response import success, success_list
from serialize import view
from services.calc import provisional_deposit
from services.ledger import (
    project_milestones, project_invoices, recompute_contract_and_final_deposit,
)
from services.cascade import (
    handoff_license_cascade, complete_waive_cascade, cancellation_cascade,
)

bp = Blueprint("projects", __name__)

SERVICE_TYPES = {"LOGO", "IDENTITY", "WEB"}


def resolve_project(studio_id, project_id):
    get_studio(studio_id)
    proj = get_or_404(db.projects, project_id, "Project not found")
    if proj["studio_id"] != studio_id:
        raise err(ERR_NOT_FOUND, "Project not found in this studio")
    return proj


@bp.route("/studios/<studio_id>/projects", methods=["POST"])
def create_project(studio_id):
    caller = authenticate()
    require_role(caller, "StudioOps")
    get_studio(studio_id)
    body = get_json_body()
    require_fields(body, "client_id", "title", "service_type", "deposit_pct")
    client_id = as_string(body["client_id"], "client_id")
    title = as_string(body["title"], "title")
    service_type = require_enum(body["service_type"], "service_type", SERVICE_TYPES)
    deposit_pct = as_number(body["deposit_pct"], "deposit_pct")

    # client_id named in body must resolve (PRD §2.9 body-referenced existence).
    client = get_or_404(db.clients, client_id, "Client not found")
    if client["studio_id"] != studio_id:
        raise err(ERR_NOT_FOUND, "Client not found in this studio")

    rec = db.create(db.projects, {
        "studio_id": studio_id,
        "client_id": client_id,
        "title": title,
        "service_type": service_type,
        "deposit_pct": deposit_pct,
        "status": "DRAFT",
        "base_scope_cents": 0,
        "contract_value_cents": 0,
        "provisional_deposit_cents": None,
        "final_deposit_cents": None,
        "deposit_collected_cents": 0,
    })
    return success(view(rec), status=201)


@bp.route("/studios/<studio_id>/projects/<project_id>", methods=["GET"])
def get_project(studio_id, project_id):
    caller = authenticate()
    require_role(caller, "StudioOps", "BillingOps", "Designer", "Client")
    proj = resolve_project(studio_id, project_id)
    require_client_owns_project(caller, proj)
    return success(view(proj), status=200)


@bp.route("/studios/<studio_id>/projects", methods=["GET"])
def list_projects(studio_id):
    caller = authenticate()
    require_role(caller, "StudioOps", "BillingOps", "Client")
    get_studio(studio_id)
    limit, offset = parse_pagination()

    records = [p for p in db.projects.values() if p["studio_id"] == studio_id]
    filter_client = request.args.get("client_id")
    filter_studio = request.args.get("studio_id")
    if filter_client is not None:
        records = [p for p in records if p["client_id"] == filter_client]
    if filter_studio is not None:
        records = [p for p in records if p["studio_id"] == filter_studio]
    # A Client may only see its own projects.
    if caller.role == "Client":
        records = [p for p in records if p["client_id"] == caller.user_id]

    window, total = paginate(records, limit, offset)
    return success_list([view(r) for r in window], limit, offset, total)


@bp.route("/studios/<studio_id>/projects/<project_id>/deposits", methods=["POST"])
def record_deposit(studio_id, project_id):
    caller = authenticate()
    require_role(caller, "BillingOps")
    proj = resolve_project(studio_id, project_id)
    body = get_json_body()
    require_fields(body, "amount_cents")
    amount = require_nonneg_int(body["amount_cents"], "amount_cents")
    proj["deposit_collected_cents"] += amount
    db.touch(proj)
    return success(view(proj), status=201)


@bp.route("/studios/<studio_id>/projects/<project_id>/activate", methods=["POST"])
def activate_project(studio_id, project_id):
    caller = authenticate()
    require_role(caller, "StudioOps")
    proj = resolve_project(studio_id, project_id)

    # DRAFT -> DISCOVERY only.
    if proj["status"] != "DRAFT":
        raise err(ERR_INVALID_STATE, "Project is not in DRAFT")

    milestones = project_milestones(project_id)
    if len(milestones) < 1:
        raise err(ERR_NO_MILESTONES, "Activation requires at least one milestone")

    client = db.clients.get(proj["client_id"])
    if client is None or client["status"] != "ACTIVE":
        raise err(ERR_CLIENT_NOT_ACTIVE, "Project client is not ACTIVE")

    base_scope = sum(m["amount_cents"] for m in milestones)
    proj["base_scope_cents"] = base_scope
    proj["contract_value_cents"] = base_scope
    proj["provisional_deposit_cents"] = provisional_deposit(
        base_scope, proj["deposit_pct"])
    proj["final_deposit_cents"] = provisional_deposit(
        proj["contract_value_cents"], proj["deposit_pct"])
    proj["status"] = "DISCOVERY"
    db.touch(proj)
    return success(view(proj), status=200)


@bp.route("/studios/<studio_id>/projects/<project_id>/advance", methods=["POST"])
def advance_project(studio_id, project_id):
    caller = authenticate()
    require_role(caller, "StudioOps")
    proj = resolve_project(studio_id, project_id)
    stage = proj["status"]

    if stage == "DISCOVERY":
        # DISCOVERY -> CONCEPT: at least one APPROVED moodboard.
        has_approved = any(
            mb["status"] == "APPROVED"
            for mb in db.moodboards.values()
            if mb["project_id"] == project_id
        )
        if not has_approved:
            raise err(ERR_MOODBOARD_NOT_APPROVED, "No approved moodboard")
        proj["status"] = "CONCEPT"
        db.touch(proj)
        return success(view(proj), status=200)

    if stage == "CONCEPT":
        # CONCEPT -> DELIVERY: at least one APPROVED concept.
        has_approved = any(
            cp["status"] == "APPROVED"
            for cp in db.concepts.values()
            if cp["project_id"] == project_id
        )
        if not has_approved:
            raise err(ERR_NO_APPROVED_CONCEPT, "No approved concept")
        proj["status"] = "DELIVERY"
        db.touch(proj)
        return success(view(proj), status=200)

    if stage == "DELIVERY":
        # DELIVERY -> HANDOFF: required deliverables ACCEPTED, then deposit gate.
        required = [
            d for d in db.deliverables.values()
            if d["project_id"] == project_id and d["is_required_for_handoff"]
        ]
        if any(d["status"] != "ACCEPTED" for d in required):
            raise err(ERR_DELIVERABLES_INCOMPLETE, "Required deliverables not accepted")
        if proj["deposit_collected_cents"] < proj["final_deposit_cents"]:
            raise err(ERR_DEPOSIT_UNPAID, "Deposit not paid in full")
        proj["status"] = "HANDOFF"
        db.touch(proj)
        # Forward cascade: bill RESERVED/CLEARED licenses.
        handoff_license_cascade(proj)
        return success(view(proj), status=200)

    # No advance transition defined from any other stage.
    raise err(ERR_INVALID_STATE, "No advance transition from current stage")


@bp.route("/studios/<studio_id>/projects/<project_id>/complete", methods=["POST"])
def complete_project(studio_id, project_id):
    caller = authenticate()
    require_role(caller, "StudioOps")
    proj = resolve_project(studio_id, project_id)

    # HANDOFF -> COMPLETED only.
    if proj["status"] != "HANDOFF":
        raise err(ERR_INVALID_STATE, "Project is not in HANDOFF")

    open_invoice = any(
        iv["status"] in ("ISSUED", "OVERDUE")
        for iv in project_invoices(project_id)
    )
    if open_invoice:
        raise err(ERR_OPEN_INVOICES, "Project has open invoices")

    proj["status"] = "COMPLETED"
    db.touch(proj)
    # Closing cascade: zero-amount PENDING milestones -> WAIVED.
    complete_waive_cascade(proj)
    return success(view(proj), status=200)


@bp.route("/studios/<studio_id>/projects/<project_id>/cancel", methods=["POST"])
def cancel_project(studio_id, project_id):
    caller = authenticate()
    require_role(caller, "StudioOps")
    proj = resolve_project(studio_id, project_id)
    stage = proj["status"]

    # Cancellable from any pre-terminal project stage with a defined cancel
    # transition: DRAFT, DISCOVERY, CONCEPT (PRD §3.2/§3.9). DELIVERY/HANDOFF
    # have no cancel transition; terminal states none.
    if stage not in ("DRAFT", "DISCOVERY", "CONCEPT"):
        raise err(ERR_INVALID_STATE, "No cancel transition from current stage")

    proj["status"] = "CANCELLED"
    db.touch(proj)
    cancellation_cascade(proj, stage)
    return success(view(proj), status=200)
