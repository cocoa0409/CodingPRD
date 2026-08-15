"""Project endpoints."""

from __future__ import annotations

from flask import Blueprint, request

import db
import errors
from middleware import require_roles
from response import success_object
from routes.common import get_body, paginate, fetch_or_404, ref_or_404
from services import core

bp = Blueprint("projects", __name__)


@bp.post("/efficiency/projects")
def create_project():
    require_roles({"ProgramManager", "Contractor"})
    body = get_body()
    lead = ref_or_404(db.leads, body.get("lead_id"), "Lead")
    customer = ref_or_404(db.customers, body.get("customer_id"), "Customer")
    contractor = ref_or_404(db.contractors, body.get("contractor_id"), "Contractor")
    program = ref_or_404(db.programs, body.get("program_id"), "Program")
    project = {
        "lead_id": lead["id"],
        "customer_id": customer["id"],
        "contractor_id": contractor["id"],
        "program_id": program["id"],
        "measure_type": body.get("measure_type"),
        "measure_cost_cents": int(body.get("measure_cost_cents") or 0),
        "estimated_annual_kwh_savings": int(body.get("estimated_annual_kwh_savings") or 0),
        "incentive_recipient": body.get("incentive_recipient"),
        "incentive_amount_cents": 0,
        "incentive_amount_provisional_cents": 0,
        "approval_snapshot_contractor_qa_bps": None,
        "status": "PROPOSED",
    }
    db.stamp_new(project)
    db.projects[project["id"]] = project
    return success_object(project, 201)


@bp.get("/efficiency/projects")
def list_projects():
    require_roles({"ProgramManager", "Contractor", "Customer"})
    items = list(db.projects.values())
    status = request.args.get("status")
    program_id = request.args.get("program_id")
    contractor_id = request.args.get("contractor_id")
    customer_id = request.args.get("customer_id")
    lead_id = request.args.get("lead_id")
    if status is not None:
        items = [p for p in items if p.get("status") == status]
    if program_id is not None:
        items = [p for p in items if p.get("program_id") == program_id]
    if contractor_id is not None:
        items = [p for p in items if p.get("contractor_id") == contractor_id]
    if customer_id is not None:
        items = [p for p in items if p.get("customer_id") == customer_id]
    if lead_id is not None:
        items = [p for p in items if p.get("lead_id") == lead_id]
    return paginate(items)


@bp.get("/efficiency/projects/<project_id>")
def get_project(project_id):
    require_roles({"ProgramManager", "Contractor", "Customer", "Inspector"})
    return success_object(fetch_or_404(db.projects, project_id, "Project"))


@bp.post("/efficiency/projects/<project_id>/approve")
def approve_project(project_id):
    require_roles({"ProgramManager"})
    project = fetch_or_404(db.projects, project_id, "Project")
    body = get_body()

    # State (priority 5)
    if project["status"] != "PROPOSED":
        raise errors.invalid_state(f"Project in {project['status']} cannot be approved")

    # OCC on Program.version (priority 6)
    program = db.programs.get(project["program_id"])
    if program is None:
        raise errors.referenced_not_found("Program not found")
    expected = body.get("expected_program_version")
    if expected is None:
        raise errors.stale_program_version("expected_program_version is required")
    if int(expected) != int(program.get("version", 1)):
        raise errors.stale_program_version()

    # Certification (priority 8)
    contractor = db.contractors.get(project["contractor_id"])
    if contractor is None:
        raise errors.referenced_not_found("Contractor not found")
    if not core.has_active_certification(contractor["id"], project.get("measure_type")):
        raise errors.certification_missing()
    if contractor.get("status") != "APPROVED":
        raise errors.invalid_state("Contractor is not APPROVED")
    lead = db.leads.get(project["lead_id"])
    if lead is None or lead.get("status") != "ACCEPTED":
        raise errors.invalid_state("Lead has not been ACCEPTED")

    # Program ACTIVE (priority 9)
    if program.get("status") != "ACTIVE":
        raise errors.program_not_active()

    # Budget (priority 17) — compute provisional first
    provisional = core.compute_incentive(project, variant="PROVISIONAL")
    if int(program.get("committed_cents", 0)) + provisional > int(program.get("budget_cents", 0)):
        raise errors.budget_exceeded()

    # Commit
    project["incentive_amount_provisional_cents"] = provisional
    project["incentive_amount_cents"] = provisional
    project["approval_snapshot_contractor_qa_bps"] = int(contractor.get("qa_score_bps") or 0)
    project["status"] = "APPROVED"
    db.touch(project)

    program["committed_cents"] = int(program.get("committed_cents", 0)) + provisional
    db.touch(program)

    # Payment shell
    if project["incentive_recipient"] == "CONTRACTOR":
        payee_id = contractor["id"]
    else:
        payee_id = project["customer_id"]
    payment = {
        "project_id": project["id"],
        "payee_role": project["incentive_recipient"],
        "payee_id": payee_id,
        "amount_cents": 0,
        "amount_provisional_cents": provisional,
        "reconciliation_delta_cents": 0,
        "status": "DRAFT",
    }
    db.stamp_new(payment)
    db.payments[payment["id"]] = payment

    return success_object(project)


@bp.post("/efficiency/projects/<project_id>/cancel")
def cancel_project(project_id):
    require_roles({"ProgramManager"})
    project = fetch_or_404(db.projects, project_id, "Project")
    if project["status"] not in ("PROPOSED", "APPROVED", "SCHEDULED", "REMEDIATION"):
        raise errors.invalid_state(f"Project in {project['status']} cannot be cancelled")

    previous_status = project["status"]
    project["status"] = "CANCELLED"
    db.touch(project)

    program = db.programs.get(project["program_id"])

    if previous_status in ("APPROVED", "SCHEDULED", "REMEDIATION"):
        # Void payment (DRAFT or AUTHORIZED depending on state)
        for pay in db.payments.values():
            if pay.get("project_id") != project["id"]:
                continue
            if previous_status == "REMEDIATION":
                if pay.get("status") in ("DRAFT", "AUTHORIZED"):
                    pay["status"] = "VOID"
                    db.touch(pay)
            else:
                if pay.get("status") == "DRAFT":
                    pay["status"] = "VOID"
                    db.touch(pay)
        # Release budget commitment
        if program is not None:
            program["committed_cents"] = int(program.get("committed_cents", 0)) - int(project.get("incentive_amount_cents") or 0)
            db.touch(program)

    if previous_status == "SCHEDULED":
        # Cascade work order cancellation
        for wo in db.work_orders.values():
            if wo.get("project_id") != project["id"]:
                continue
            if wo.get("status") in ("SCHEDULED", "DRAFT"):
                wo["status"] = "CANCELLED"
                db.touch(wo)

    return success_object(project)


@bp.post("/efficiency/projects/<project_id>/work_orders")
def create_work_order(project_id):
    role, user_id = require_roles({"Contractor"})
    project = fetch_or_404(db.projects, project_id, "Project")
    body = get_body()
    contractor = ref_or_404(db.contractors, body.get("contractor_id"), "Contractor")

    # State check (priority 5)
    if project["status"] != "APPROVED":
        raise errors.invalid_state(f"Project in {project['status']} cannot accept work orders")

    # Ownership: caller must be the project's contractor
    if project.get("contractor_id") != user_id:
        raise errors.not_resource_owner()
    if contractor["id"] != user_id:
        raise errors.not_resource_owner()

    scheduled_on = body.get("scheduled_on")
    duration_hours = int(body.get("duration_hours") or 0)
    direct_install = bool(body.get("direct_install") or False)

    # Calendar overlap check only when direct_install == false
    if not direct_install and scheduled_on is not None:
        if core.has_calendar_conflict(contractor["id"], scheduled_on, duration_hours):
            raise errors.schedule_conflict()

    wo = {
        "project_id": project["id"],
        "contractor_id": contractor["id"],
        "scheduled_on": scheduled_on,
        "duration_hours": duration_hours,
        "direct_install": direct_install,
        "assigned_inspector_id": None,
        "completed_on": None,
        "status": "DRAFT" if direct_install else "SCHEDULED",
    }
    db.stamp_new(wo)
    db.work_orders[wo["id"]] = wo

    # First WorkOrder creation advances the project APPROVED -> SCHEDULED
    project["status"] = "SCHEDULED"
    db.touch(project)

    return success_object(wo, 201)
