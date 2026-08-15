"""TIProject lifecycle endpoints."""

from flask import Blueprint, request

from db import store
from middleware import require_roles, check_tenant_ownership, get_project_tenant_ownership
from response import success_object, success_created
from errors import (
    not_found, invalid_request, invalid_state, APIError,
    ERR_ACTIVE_PROJECT_EXISTS, ERR_PREREQUISITE_NOT_MET,
    ERR_PROPERTY_CONSTRUCTION_CAPACITY, ERR_INVALID_WINDOW,
    ERR_CONSTRUCTION_WINDOW_NOT_ENDED,
    ERR_LIFE_SAFETY_ITEM_OPEN, ERR_PUNCH_ITEMS_OPEN,
)
from services.util import (
    make_common_fields, bump_version,
    require_fields, is_int, is_str, parse_iso8601, to_iso_z, logical_clock_dt,
)
from services import calc, cascade

bp = Blueprint("projects", __name__)


def _get_project_or_404(pid):
    p = store.ti_projects.get(pid)
    if not p:
        raise not_found("TIProject not found")
    return p


def _get_project_lease(project):
    return store.leases.get(project["lease_id"])


# ---------------------------------------------------------------------------
# POST /api/leases/{id}/ti-projects — create a project
# ---------------------------------------------------------------------------

@bp.route("/api/leases/<id>/ti-projects", methods=["POST"])
def create_ti_project(id):
    require_roles("LandlordPM")
    lease = store.leases.get(id)
    if not lease:
        raise not_found("Lease not found")
    if lease["status"] != "ACTIVE":
        raise invalid_state("Lease must be ACTIVE to create a TI project")

    body = request.get_json(silent=True) or {}
    require_fields(body, ["project_name", "base_contract_cents"])
    if not is_str(body["project_name"]):
        raise invalid_request("project_name must be a string")
    if not is_int(body["base_contract_cents"]) or body["base_contract_cents"] < 0:
        raise invalid_request("base_contract_cents must be integer >= 0")

    # Only one non-terminal TIProject per lease
    for p in store.ti_projects.values():
        if p["lease_id"] == id and p["status"] not in ("COMPLETED", "CANCELLED"):
            raise APIError(ERR_ACTIVE_PROJECT_EXISTS, 409,
                           "Lease already has a non-terminal TI project")

    rec = make_common_fields()
    rec.update({
        "lease_id": id,
        "project_name": body["project_name"],
        "base_contract_cents": body["base_contract_cents"],
        "allowance_total_cents": 0,
        "status": "INITIATED",
        "posture": "OPEN",
        "construction_start_date": None,
        "construction_end_date": None,
        "substantial_completion_date": None,
        "occupancy_certificate_ref": None,
        "total_cost_cents": 0,
        "allowance_consumed_cents": 0,
        "provisional_allowance_consumed_cents": 0,
        "allowance_remaining_cents": 0,
        "overage_cents": 0,
        "retainage_held_cents": 0,
        "retainage_released_cents": 0,
    })
    store.ti_projects[rec["id"]] = rec
    return success_created(rec)


# ---------------------------------------------------------------------------
# GET /api/ti-projects/{id}
# ---------------------------------------------------------------------------

@bp.route("/api/ti-projects/<id>", methods=["GET"])
def get_ti_project(id):
    user_id, role = require_roles(
        "LandlordPM", "LandlordApprover", "TenantRep", "ContractorRep", "BuildingEngineer"
    )
    proj = _get_project_or_404(id)
    if role == "TenantRep":
        check_tenant_ownership(user_id, proj["lease_id"])
    return success_object(proj)


# ---------------------------------------------------------------------------
# Phase advancement endpoints
# ---------------------------------------------------------------------------

@bp.route("/api/ti-projects/<id>/begin-plan-review", methods=["POST"])
def begin_plan_review(id):
    require_roles("LandlordPM")
    proj = _get_project_or_404(id)
    if proj["status"] != "WORK_LETTER_NEGOTIATION":
        raise invalid_state("Project must be in WORK_LETTER_NEGOTIATION")
    # Exactly one EXECUTED WorkLetter
    executed = [
        wl for wl in store.work_letters.values()
        if wl["project_id"] == id and wl["status"] == "EXECUTED"
    ]
    if len(executed) != 1:
        raise APIError(ERR_PREREQUISITE_NOT_MET, 422,
                       "Exactly one EXECUTED WorkLetter is required")
    proj["status"] = "PLAN_REVIEW"
    bump_version(proj)
    return success_object(proj)


@bp.route("/api/ti-projects/<id>/begin-pre-construction", methods=["POST"])
def begin_pre_construction(id):
    require_roles("LandlordPM")
    proj = _get_project_or_404(id)
    if proj["status"] != "PLAN_REVIEW":
        raise invalid_state("Project must be in PLAN_REVIEW")
    approved = [
        ps for ps in store.plan_submissions.values()
        if ps["project_id"] == id and ps["status"] == "APPROVED"
    ]
    if not approved:
        raise APIError(ERR_PREREQUISITE_NOT_MET, 422,
                       "At least one APPROVED PlanSubmission is required")
    proj["status"] = "PRE_CONSTRUCTION"
    bump_version(proj)
    return success_object(proj)


@bp.route("/api/ti-projects/<id>/start-construction", methods=["POST"])
def start_construction(id):
    require_roles("LandlordPM")
    proj = _get_project_or_404(id)
    if proj["status"] != "PRE_CONSTRUCTION":
        raise invalid_state("Project must be in PRE_CONSTRUCTION")

    body = request.get_json(silent=True) or {}
    require_fields(body, ["construction_start_date", "construction_end_date"])
    try:
        start_dt = parse_iso8601(body["construction_start_date"])
    except Exception:
        raise invalid_request("construction_start_date must be valid ISO8601")
    try:
        end_dt = parse_iso8601(body["construction_end_date"])
    except Exception:
        raise invalid_request("construction_end_date must be valid ISO8601")

    start_iso = to_iso_z(start_dt)
    end_iso = to_iso_z(end_dt)

    # Business checks in PRD §2.7 order: capacity -> window shape -> engagement prereq
    if not calc.check_property_capacity(proj, start_iso, end_iso):
        raise APIError(ERR_PROPERTY_CONSTRUCTION_CAPACITY, 409,
                       "Property construction capacity exceeded")

    if end_dt <= start_dt:
        raise APIError(ERR_INVALID_WINDOW, 422,
                       "construction_end_date must be strictly after construction_start_date")

    has_active = any(
        e for e in store.contractor_engagements.values()
        if e["project_id"] == id and e["status"] == "ACTIVE"
    )
    if not has_active:
        raise APIError(ERR_PREREQUISITE_NOT_MET, 422,
                       "At least one ACTIVE ContractorEngagement is required")

    # Side effects
    proj["construction_start_date"] = start_iso
    proj["construction_end_date"] = end_iso
    proj["status"] = "CONSTRUCTION"
    bump_version(proj)

    lease = _get_project_lease(proj)
    if lease:
        space = store.lease_spaces.get(lease["space_id"])
        if space and space["status"] == "LEASED":
            space["status"] = "UNDER_CONSTRUCTION"
            bump_version(space)

    return success_object(proj)


@bp.route("/api/ti-projects/<id>/begin-punch", methods=["POST"])
def begin_punch(id):
    require_roles("LandlordPM")
    proj = _get_project_or_404(id)
    if proj["status"] != "CONSTRUCTION":
        raise invalid_state("Project must be in CONSTRUCTION")

    # Clock >= construction_end_date
    clock = logical_clock_dt()
    end_dt = parse_iso8601(proj["construction_end_date"])
    if clock < end_dt:
        raise APIError(ERR_CONSTRUCTION_WINDOW_NOT_ENDED, 422,
                       "Current logical clock has not reached construction_end_date")

    # All milestones on all engagements of the project must be terminal
    eng_ids = {
        e["id"] for e in store.contractor_engagements.values()
        if e["project_id"] == id
    }
    for m in store.schedule_milestones.values():
        if m["engagement_id"] in eng_ids and m["status"] not in ("COMPLETED", "CANCELLED"):
            raise invalid_state(
                "All ScheduleMilestones must be in terminal state (COMPLETED or CANCELLED)"
            )

    proj["status"] = "PUNCH"
    bump_version(proj)
    return success_object(proj)


@bp.route("/api/ti-projects/<id>/issue-occupancy-certificate", methods=["POST"])
def issue_occupancy_certificate(id):
    require_roles("LandlordPM")
    proj = _get_project_or_404(id)
    if proj["status"] != "PUNCH":
        raise invalid_state("Project must be in PUNCH")

    body = request.get_json(silent=True) or {}
    require_fields(body, ["occupancy_certificate_ref", "issued_on", "delay_responsibility"])
    if not is_str(body["occupancy_certificate_ref"]):
        raise invalid_request("occupancy_certificate_ref must be a string")
    try:
        issued_dt = parse_iso8601(body["issued_on"])
    except Exception:
        raise invalid_request("issued_on must be valid ISO8601")
    if body["delay_responsibility"] not in ("NONE", "LANDLORD", "TENANT"):
        raise invalid_request("delay_responsibility must be NONE, LANDLORD, or TENANT")

    # Punch list gate: LIFE_SAFETY first, then all items
    punch_items = [
        p for p in store.punch_items.values() if p["project_id"] == id
    ]
    life_safety_open = [
        p for p in punch_items
        if p["severity"] == "LIFE_SAFETY" and p["status"] != "VERIFIED"
    ]
    if life_safety_open:
        raise APIError(ERR_LIFE_SAFETY_ITEM_OPEN, 422,
                       "LIFE_SAFETY punch items are not yet VERIFIED")
    any_open = [p for p in punch_items if p["status"] != "VERIFIED"]
    if any_open:
        raise APIError(ERR_PUNCH_ITEMS_OPEN, 422,
                       "Punch items are not yet VERIFIED")

    # Set certificate fields
    proj["occupancy_certificate_ref"] = body["occupancy_certificate_ref"]
    proj["substantial_completion_date"] = to_iso_z(issued_dt)
    proj["status"] = "CLOSEOUT"
    bump_version(proj)

    # Lease abatement
    lease = _get_project_lease(proj)
    if lease:
        lease["delay_responsibility"] = body["delay_responsibility"]
        calc.compute_rent_abatement(lease, proj["substantial_completion_date"])
        bump_version(lease)

        # Space back to LEASED
        space = store.lease_spaces.get(lease["space_id"])
        if space and space["status"] == "UNDER_CONSTRUCTION":
            space["status"] = "LEASED"
            bump_version(space)

    # Auto-issue DRAFT overage invoices (due date from certificate issued_on)
    for inv in store.overage_invoices.values():
        if inv["project_id"] == id and inv["status"] == "DRAFT":
            inv["status"] = "ISSUED"
            inv["due_date"] = calc.compute_invoice_due_date(
                proj["substantial_completion_date"]
            )
            bump_version(inv)

    return success_object(proj)


@bp.route("/api/ti-projects/<id>/complete", methods=["POST"])
def complete_project(id):
    require_roles("LandlordPM")
    proj = _get_project_or_404(id)
    if proj["status"] != "CLOSEOUT":
        raise invalid_state("Project must be in CLOSEOUT")

    # Every draw terminal
    for d in store.disbursement_requests.values():
        if d["project_id"] == id and d["status"] not in ("PAID", "REJECTED", "VOIDED"):
            raise invalid_state("All DisbursementRequests must be in terminal state")
    # Every invoice terminal
    for inv in store.overage_invoices.values():
        if inv["project_id"] == id and inv["status"] not in ("PAID", "VOID"):
            raise invalid_state("All OverageInvoices must be in terminal state")
    # Every engagement terminal
    for eng in store.contractor_engagements.values():
        if eng["project_id"] == id and eng["status"] not in ("TERMINATED", "COMPLETED"):
            raise invalid_state("All ContractorEngagements must be in terminal state")

    proj["status"] = "COMPLETED"
    bump_version(proj)
    return success_object(proj)


@bp.route("/api/ti-projects/<id>/cancel", methods=["POST"])
def cancel_project(id):
    require_roles("LandlordPM")
    proj = _get_project_or_404(id)
    if proj["status"] in ("COMPLETED", "CANCELLED"):
        raise invalid_state("Project is already in a terminal state")

    lease_id = proj["lease_id"]
    cascade.cancel_project(proj)
    proj["status"] = "CANCELLED"
    bump_version(proj)

    # If all projects of the lease are now terminal, terminate the lease
    cascade.maybe_terminate_lease(lease_id)

    return success_object(proj)
