"""RebuildProject endpoints (PRD §3.3, §3.4, §3.6-§3.9)."""

from flask import Blueprint, request

import constants as C
from calc import compute_line_total, compute_quote, escalation_surcharge
from db import bump, new_record, sorted_records, store
from errors import (
    ApiError,
    ERR_COMMERCIAL_NOT_APPROVED,
    ERR_CREDIT_LIMIT_EXCEEDED,
    ERR_DECISION_OVERRIDE_NEEDS_REASON,
    ERR_INSUFFICIENT_STOCK,
    ERR_INVALID_STATE,
    ERR_LINES_OUTSTANDING,
    ERR_PART_SUPERSEDED,
    ERR_QUOTE_REQUIRED,
    ERR_QUOTE_STALE,
    ERR_STAGES_NOT_INSTALLED,
    ERR_STALE_PROJECT_VERSION,
    ERR_TRADE_IN_ALREADY_APPLIED,
    ERR_TRADE_IN_NOT_APPLICABLE,
    not_found,
)
from middleware import forbidden, require_roles
from response import list_response, success
from serializers import serialize, serialize_list
from services import (
    cancel_project_cascade,
    offer_applied_to_project,
    project_lines,
    project_stages,
    project_training_record,
)
from util import (
    get_body,
    iso3,
    add_months,
    pagination_params,
    paginate,
    req_enum,
    req_int,
    req_str,
    opt_str,
)
from routes.common import check_customer_ownership, customer_owns, get_or_404

bp = Blueprint("projects", __name__)

DECISIONS = ("RETROFIT_ONLY", "MECHANICAL_REBUILD", "FULL_REBUILD")


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------
@bp.get("/api/projects/<pid>")
@require_roles("ProjectManager", "Customer", "PlatformAdmin", "RebuildEngineer", "QualityInspector")
def get_project(user_id, role, pid):
    rec = get_or_404(store.projects, pid, "project")
    check_customer_ownership(user_id, role, "project", rec)
    return success(serialize(rec))


@bp.get("/api/projects")
@require_roles("ProjectManager", "Customer", "PlatformAdmin")
def list_projects(user_id, role):
    limit, offset = pagination_params()
    items = sorted_records(store.projects)
    for param in ("machine_id", "customer_id", "assessment_id"):
        value = request.args.get(param)
        if value is not None:
            items = [p for p in items if p[param] == value]
    if role == "Customer":
        items = [p for p in items if customer_owns(user_id, "project", p)]
    page, meta = paginate(items, limit, offset)
    return list_response(serialize_list(page), meta)


# ---------------------------------------------------------------------------
# Decision (SCOPED -> DECIDED)
# ---------------------------------------------------------------------------
@bp.post("/api/projects/<pid>/decision")
@require_roles("ProjectManager")
def record_decision(user_id, role, pid):
    body = get_body()
    decision = req_enum(body, "decision", DECISIONS)
    assigned_engineer_id = req_str(body, "assigned_engineer_id")
    decision_reason = opt_str(body, "decision_reason")
    project = get_or_404(store.projects, pid, "project")
    if project["work_status"] != "SCOPED":
        raise ApiError(
            ERR_INVALID_STATE,
            f"project in work_status {project['work_status']} cannot record a decision",
            409,
        )
    assessment = store.assessments[project["assessment_id"]]
    if decision != assessment["recommended_path"]:
        if decision_reason is None or decision_reason.strip() == "":
            raise ApiError(
                ERR_DECISION_OVERRIDE_NEEDS_REASON,
                "decision differs from the assessment's recommended_path and requires a non-empty decision_reason",
                409,
            )
    project["decision"] = decision
    project["decision_reason"] = decision_reason
    project["assigned_engineer_id"] = assigned_engineer_id
    project["warranty_months"] = C.WARRANTY_MONTHS[decision]
    project["work_status"] = "DECIDED"
    bump(project)
    return success(serialize(project))


# ---------------------------------------------------------------------------
# Quote lifecycle (commercial dimension runs parallel to work dimension)
# ---------------------------------------------------------------------------
@bp.post("/api/projects/<pid>/quote")
@require_roles("ProjectManager")
def compute_quote_endpoint(user_id, role, pid):
    body = get_body()
    expected_version = req_int(body, "expected_project_version")
    project = get_or_404(store.projects, pid, "project")
    # Gate 5: OCC on RebuildProject.version.
    if expected_version != project["version"]:
        raise ApiError(
            ERR_STALE_PROJECT_VERSION,
            "expected_project_version does not match the project's current version",
            412,
        )
    if project["work_status"] != "DECIDED":
        raise ApiError(
            ERR_INVALID_STATE,
            "quote computation requires work_status DECIDED",
            409,
        )
    assessment = store.assessments[project["assessment_id"]]
    result = compute_quote(project, project_lines(pid), assessment)
    project["base_price_cents"] = result["base_price_cents"]
    project["parts_total_cents"] = result["parts_total_cents"]
    project["labor_cents"] = result["labor_cents"]
    project["discount_cents"] = result["discount_cents"]
    project["quote_price_cents"] = result["quote_price_cents"]
    project["quote_revision"] += 1
    project["quote_stale"] = False
    if project["commercial_status"] == "QUOTE_SENT":
        # Renegotiation revert: commercial dimension back to QUOTE_DRAFT.
        project["commercial_status"] = "QUOTE_DRAFT"
    bump(project)
    return success(serialize(project))


@bp.post("/api/projects/<pid>/quote/send")
@require_roles("ProjectManager")
def send_quote(user_id, role, pid):
    project = get_or_404(store.projects, pid, "project")
    if project["commercial_status"] != "QUOTE_DRAFT":
        raise ApiError(
            ERR_INVALID_STATE,
            f"quote cannot be sent from commercial_status {project['commercial_status']}",
            409,
        )
    if project["quote_revision"] == 0:
        raise ApiError(ERR_QUOTE_REQUIRED, "no quote has been computed", 409)
    if project["quote_stale"]:
        raise ApiError(
            ERR_QUOTE_STALE, "part lines changed after the last quote computation", 409
        )
    project["commercial_status"] = "QUOTE_SENT"
    bump(project)
    return success(serialize(project))


@bp.post("/api/projects/<pid>/quote/approve")
@require_roles("Customer")
def approve_quote(user_id, role, pid):
    project = get_or_404(store.projects, pid, "project")
    if project["customer_id"] != user_id:
        raise forbidden("only the project's customer may approve the quote")
    if project["commercial_status"] != "QUOTE_SENT":
        raise ApiError(
            ERR_INVALID_STATE,
            f"quote cannot be approved from commercial_status {project['commercial_status']}",
            409,
        )
    if project["quote_stale"]:
        raise ApiError(
            ERR_QUOTE_STALE, "part lines changed after the last quote computation", 409
        )
    customer = store.customers[project["customer_id"]]
    if project["quote_price_cents"] > customer["credit_limit_cents"]:
        raise ApiError(
            ERR_CREDIT_LIMIT_EXCEEDED,
            "quote_price_cents exceeds the customer's credit_limit_cents",
            409,
        )
    project["commercial_status"] = "APPROVED"
    bump(project)
    return success(serialize(project))


# ---------------------------------------------------------------------------
# Parts sourcing (DECIDED -> PARTS_SOURCING) and part lines
# ---------------------------------------------------------------------------
@bp.post("/api/projects/<pid>/begin-sourcing")
@require_roles("ProjectManager")
def begin_sourcing(user_id, role, pid):
    project = get_or_404(store.projects, pid, "project")
    if project["work_status"] != "DECIDED":
        raise ApiError(
            ERR_INVALID_STATE,
            "begin-sourcing requires work_status DECIDED",
            409,
        )
    if project["commercial_status"] != "APPROVED":
        raise ApiError(
            ERR_COMMERCIAL_NOT_APPROVED,
            "commercial_status must be APPROVED before parts sourcing opens",
            409,
        )
    lines = project_lines(pid)
    if not lines:
        raise ApiError(
            ERR_LINES_OUTSTANDING, "at least one part line must exist", 409
        )
    # Atomic stock gate: PENDING lines on ACTIVE parts in ascending creation
    # order, with reservations projected cumulatively per part (a reserve that
    # would drive available_quantity negative is rejected); the first failure
    # aborts with no reservations applied.
    pending_active = [
        l
        for l in lines
        if l["status"] == "PENDING" and store.parts[l["part_id"]]["oem_status"] == "ACTIVE"
    ]
    projected = {}
    for line in pending_active:
        part = store.parts[line["part_id"]]
        effective_available = part["available_quantity"] - projected.get(part["id"], 0)
        if effective_available < line["quantity"]:
            raise ApiError(
                ERR_INSUFFICIENT_STOCK,
                f"part {part['id']} has insufficient available quantity",
                409,
            )
        projected[part["id"]] = projected.get(part["id"], 0) + line["quantity"]
    for line in lines:
        if line["status"] != "PENDING":
            continue
        part = store.parts[line["part_id"]]
        if part["oem_status"] == "ACTIVE":
            line["status"] = "RESERVED"
            bump(line)
            part["reserved_quantity"] += line["quantity"]
            part["available_quantity"] = part["stock_quantity"] - part["reserved_quantity"]
            bump(part)
        else:  # OBSOLETE -> reverse engineering
            line["status"] = "RE_PENDING"
            bump(line)
            job = new_record(
                {
                    "part_line_id": line["id"],
                    "project_id": pid,
                    "part_id": part["id"],
                    "revision_count": 0,
                    "re_cost_cents": None,
                    "fabricated_by_id": None,
                    "validated_by_id": None,
                    "status": "REQUESTED",
                }
            )
            store.re_jobs[job["id"]] = job
    machine = store.machines[project["machine_id"]]
    if machine["status"] == "ASSESSED":
        machine["status"] = "IN_PROJECT"
        bump(machine)
    project["work_status"] = "PARTS_SOURCING"
    bump(project)
    return success(serialize(project))


@bp.post("/api/projects/<pid>/part-lines")
@require_roles("ProjectManager")
def add_part_line(user_id, role, pid):
    body = get_body()
    part_id = req_str(body, "part_id")
    quantity = req_int(body, "quantity", minimum=1)
    project = get_or_404(store.projects, pid, "project")
    part = get_or_404(store.parts, part_id, "part")
    if project["work_status"] != "DECIDED":
        raise ApiError(
            ERR_INVALID_STATE, "part lines may only be added while DECIDED", 409
        )
    if part["oem_status"] == "SUPERSEDED":
        raise ApiError(
            ERR_PART_SUPERSEDED,
            "part is SUPERSEDED; order its replacement instead",
            409,
        )
    obs_multiplier = (
        float(C.OBS_MULTIPLIER_OBSOLETE)
        if part["oem_status"] == "OBSOLETE"
        else float(C.OBS_MULTIPLIER_NORMAL)
    )
    line_total = compute_line_total(quantity, part["unit_cost_cents"], obs_multiplier)
    rec = new_record(
        {
            "project_id": pid,
            "part_id": part_id,
            "quantity": quantity,
            "unit_price_cents": part["unit_cost_cents"],
            "obs_multiplier": obs_multiplier,
            "line_total_cents": line_total,
            "status": "PENDING",
        }
    )
    store.part_lines[rec["id"]] = rec
    # Lines changed after a computed quote -> raise quote_stale (PRD §2.10).
    if project["quote_revision"] >= 1:
        project["quote_stale"] = True
        bump(project)
    return success(serialize(rec), status=201)


@bp.post("/api/projects/<pid>/start-rebuild")
@require_roles("ProjectManager")
def start_rebuild(user_id, role, pid):
    project = get_or_404(store.projects, pid, "project")
    if project["work_status"] != "PARTS_SOURCING":
        raise ApiError(
            ERR_INVALID_STATE,
            "start-rebuild requires work_status PARTS_SOURCING",
            409,
        )
    outstanding = [
        l
        for l in project_lines(pid)
        if l["status"] in ("PENDING", "RESERVED", "RE_PENDING")
    ]
    if outstanding:
        raise ApiError(
            ERR_LINES_OUTSTANDING,
            "all part lines must be FULFILLED, RE_FULFILLED or CANCELLED",
            409,
        )
    project["work_status"] = "REBUILD_IN_PROGRESS"
    bump(project)
    return success(serialize(project))


@bp.post("/api/projects/<pid>/declare-ready")
@require_roles("RebuildEngineer")
def declare_ready(user_id, role, pid):
    project = get_or_404(store.projects, pid, "project")
    if project["assigned_engineer_id"] != user_id:
        raise forbidden("only the assigned rebuild engineer may declare readiness")
    if project["work_status"] not in ("REBUILD_IN_PROGRESS", "REWORK"):
        raise ApiError(
            ERR_INVALID_STATE,
            f"declare-ready is not allowed from work_status {project['work_status']}",
            409,
        )
    project["work_status"] = "AWAITING_ACCEPTANCE"
    bump(project)
    return success(serialize(project))


# ---------------------------------------------------------------------------
# Escalation resolution
# ---------------------------------------------------------------------------
@bp.post("/api/projects/<pid>/escalation/resolve")
@require_roles("ProjectManager")
def resolve_escalation(user_id, role, pid):
    body = get_body()
    action = req_enum(body, "action", ("RETRY", "CANCEL"))
    project = get_or_404(store.projects, pid, "project")
    if project["work_status"] != "ESCALATED":
        raise ApiError(
            ERR_INVALID_STATE,
            "escalation resolve requires work_status ESCALATED",
            409,
        )
    if action == "RETRY":
        project["work_status"] = "AWAITING_ACCEPTANCE"
        project["consecutive_fail_count"] = 0
        project["escalation_count"] += 1
        project["rework_cost_cents"] += escalation_surcharge(project["quote_price_cents"])
        bump(project)
    else:  # CANCEL
        project["work_status"] = "CANCELLED"
        bump(project)
        cancel_project_cascade(project)
    return success(serialize(project))


# ---------------------------------------------------------------------------
# Training kickoff (ACCEPTED -> TRAINING_IN_PROGRESS)
# ---------------------------------------------------------------------------
@bp.post("/api/projects/<pid>/begin-training")
@require_roles("ProjectManager")
def begin_training(user_id, role, pid):
    body = get_body()
    trainer_id = req_str(body, "trainer_id")
    project = get_or_404(store.projects, pid, "project")
    if project["work_status"] != "ACCEPTED":
        raise ApiError(
            ERR_INVALID_STATE,
            "begin-training requires work_status ACCEPTED",
            409,
        )
    rec = project_training_record(pid)
    if rec is None:
        raise ApiError(
            ERR_INVALID_STATE, "training record does not exist for this project", 409
        )
    rec["trainer_id"] = trainer_id
    bump(rec)
    project["work_status"] = "TRAINING_IN_PROGRESS"
    bump(project)
    return success(serialize(rec))


# ---------------------------------------------------------------------------
# Delivery (HANDOVER_READY -> WARRANTY_ACTIVE)
# ---------------------------------------------------------------------------
@bp.post("/api/projects/<pid>/deliver")
@require_roles("ProjectManager")
def deliver_project(user_id, role, pid):
    project = get_or_404(store.projects, pid, "project")
    if project["work_status"] != "HANDOVER_READY":
        raise ApiError(
            ERR_INVALID_STATE, "deliver requires work_status HANDOVER_READY", 409
        )
    not_installed = [
        s
        for s in project_stages(pid)
        if s["status"] not in ("INSTALLED", "CANCELLED")
    ]
    if not_installed:
        raise ApiError(
            ERR_STAGES_NOT_INSTALLED,
            "every shipment stage must be INSTALLED or CANCELLED before delivery",
            409,
        )
    from db import clock

    project["delivery_date"] = clock.iso()
    warranty_end_dt = add_months(clock.now, project["warranty_months"])
    project["warranty_end"] = iso3(warranty_end_dt)
    project["_warranty_end_dt"] = warranty_end_dt
    machine = store.machines[project["machine_id"]]
    if machine["status"] == "IN_PROJECT":
        machine["status"] = "RETURNED"
        bump(machine)
    project["work_status"] = "WARRANTY_ACTIVE"
    bump(project)
    return success(serialize(project))


# ---------------------------------------------------------------------------
# Cancellation (SCOPED / DECIDED / PARTS_SOURCING -> CANCELLED)
# ---------------------------------------------------------------------------
@bp.post("/api/projects/<pid>/cancel")
@require_roles("ProjectManager")
def cancel_project(user_id, role, pid):
    project = get_or_404(store.projects, pid, "project")
    if project["work_status"] not in ("SCOPED", "DECIDED", "PARTS_SOURCING"):
        raise ApiError(
            ERR_INVALID_STATE,
            f"project in work_status {project['work_status']} cannot be cancelled",
            409,
        )
    project["work_status"] = "CANCELLED"
    bump(project)
    cancel_project_cascade(project)
    return success(serialize(project))


# ---------------------------------------------------------------------------
# Trade-in credit application / revocation (PRD §3.9, conservation §2.10)
# ---------------------------------------------------------------------------
@bp.post("/api/projects/<pid>/trade-in/apply")
@require_roles("ProjectManager")
def apply_trade_in(user_id, role, pid):
    body = get_body()
    offer_id = req_str(body, "offer_id")
    project = get_or_404(store.projects, pid, "project")
    offer = store.offers.get(offer_id)
    if offer is None:
        raise not_found(f"trade-in offer {offer_id} does not exist")
    if (
        offer["status"] != "ACCEPTED"
        or offer["customer_id"] != project["customer_id"]
        or (offer["applied_project_id"] is not None and offer["applied_project_id"] != pid)
    ):
        raise ApiError(
            ERR_TRADE_IN_NOT_APPLICABLE,
            "offer must be ACCEPTED, belong to the project's customer, and not be applied to another project",
            409,
        )
    if project["applied_trade_in_credit_cents"] != 0:
        raise ApiError(
            ERR_TRADE_IN_ALREADY_APPLIED,
            "project already carries an applied trade-in credit",
            409,
        )
    project["applied_trade_in_credit_cents"] = offer["residual_value_cents"]
    project["quote_price_cents"] -= offer["residual_value_cents"]
    offer["applied_project_id"] = pid
    bump(offer)
    bump(project)
    return success(serialize(project))


@bp.post("/api/projects/<pid>/trade-in/revoke")
@require_roles("ProjectManager")
def revoke_trade_in(user_id, role, pid):
    project = get_or_404(store.projects, pid, "project")
    if project["applied_trade_in_credit_cents"] == 0:
        raise ApiError(
            ERR_TRADE_IN_ALREADY_APPLIED,
            "project carries no applied trade-in credit to revoke",
            409,
        )
    applied = project["applied_trade_in_credit_cents"]
    project["quote_price_cents"] += applied
    project["applied_trade_in_credit_cents"] = 0
    offer = offer_applied_to_project(pid)
    if offer is not None:
        offer["applied_project_id"] = None
        bump(offer)
    bump(project)
    return success(serialize(project))
