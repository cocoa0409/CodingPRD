"""Inspection endpoints."""

from __future__ import annotations

from datetime import timedelta

from flask import Blueprint, request

import db
import errors
from middleware import require_roles
from response import success_object
from routes.common import get_body, paginate, fetch_or_404, ref_or_404
from services import core

bp = Blueprint("inspections", __name__)


@bp.post("/efficiency/inspections")
def create_inspection():
    role, user_id = require_roles({"Inspector"})
    body = get_body()
    work_order = ref_or_404(db.work_orders, body.get("work_order_id"), "WorkOrder")
    project = ref_or_404(db.projects, body.get("project_id"), "Project")
    inspector = ref_or_404(db.inspectors, body.get("inspector_id"), "Inspector")

    # Caller must be the named inspector (entity-backed ownership on request)
    if inspector["id"] != user_id:
        raise errors.not_resource_owner()

    # State: project must be INSTALLED (first inspection) or REMEDIATION (re-inspection)
    if project.get("status") not in ("INSTALLED", "REMEDIATION"):
        raise errors.invalid_state(f"Project in {project['status']} cannot accept an inspection")

    # Segregation of duties (priority 7)
    if work_order.get("contractor_id") in (inspector.get("excluded_contractor_ids") or []):
        raise errors.inspector_conflict()

    # Project must have at least one COMPLETED work order; acting inspector
    # must match the assigned_inspector_id on that completed order.
    completed_wos = [
        w for w in db.work_orders.values()
        if w.get("project_id") == project["id"] and w.get("status") == "COMPLETED"
    ]
    if not completed_wos:
        raise errors.invalid_state("Project has no COMPLETED work order")

    # Use the most recently completed WO for the assignment match.
    completed_wos.sort(key=lambda w: (w.get("completed_on") or "", w.get("created_at") or ""), reverse=True)
    latest_completed = completed_wos[0]
    if latest_completed.get("assigned_inspector_id") != user_id:
        raise errors.not_resource_owner("Acting inspector is not the assigned inspector for this work order")

    if project.get("status") == "REMEDIATION":
        # Re-inspection must occur on or before the most recent FAIL's
        # remediation_required_by.
        prior_fails = [
            i for i in db.inspections.values()
            if i.get("project_id") == project["id"]
            and i.get("status") == "RECORDED"
            and i.get("outcome") == "FAIL"
        ]
        if prior_fails:
            prior_fails.sort(key=lambda i: (i.get("updated_at") or "", i.get("created_at") or ""), reverse=True)
            deadline_iso = prior_fails[0].get("remediation_required_by")
            if deadline_iso is not None and db.get_clock() > db.parse_dt(deadline_iso):
                raise errors.remediation_window_expired()

    inspection = {
        "work_order_id": work_order["id"],
        "project_id": project["id"],
        "inspector_id": inspector["id"],
        "scheduled_on": body.get("scheduled_on"),
        "outcome": "PENDING",
        "score_bps": None,
        "failure_reasons": list(body.get("failure_reasons") or []),
        "remediation_required_by": None,
        "status": "SCHEDULED",
    }
    db.stamp_new(inspection)
    db.inspections[inspection["id"]] = inspection

    # Advance the project
    project["status"] = "INSPECTING"
    db.touch(project)

    return success_object(inspection, 201)


@bp.get("/efficiency/inspections")
def list_inspections():
    require_roles({"ProgramManager", "Contractor", "Inspector"})
    items = list(db.inspections.values())
    project_id = request.args.get("project_id")
    work_order_id = request.args.get("work_order_id")
    inspector_id = request.args.get("inspector_id")
    outcome = request.args.get("outcome")
    status = request.args.get("status")
    if project_id is not None:
        items = [i for i in items if i.get("project_id") == project_id]
    if work_order_id is not None:
        items = [i for i in items if i.get("work_order_id") == work_order_id]
    if inspector_id is not None:
        items = [i for i in items if i.get("inspector_id") == inspector_id]
    if outcome is not None:
        items = [i for i in items if i.get("outcome") == outcome]
    if status is not None:
        items = [i for i in items if i.get("status") == status]
    return paginate(items)


@bp.get("/efficiency/inspections/<inspection_id>")
def get_inspection(inspection_id):
    require_roles({"ProgramManager", "Contractor", "Inspector"})
    return success_object(fetch_or_404(db.inspections, inspection_id, "Inspection"))


@bp.post("/efficiency/inspections/<inspection_id>/record")
def record_inspection(inspection_id):
    role, user_id = require_roles({"Inspector"})
    inspection = fetch_or_404(db.inspections, inspection_id, "Inspection")

    # State (priority 5)
    if inspection["status"] != "SCHEDULED":
        raise errors.invalid_state(f"Inspection in {inspection['status']} cannot be recorded")

    # Segregation-of-duties (priority 7) — the screen is re-checked against
    # the CALLER's exclusion list (PRD 3.6: "the segregation rule is
    # re-checked against the work order's contractor ... and the caller must
    # be the inspection's own inspector_id").
    work_order = db.work_orders.get(inspection["work_order_id"])
    if work_order is None:
        raise errors.referenced_not_found("WorkOrder not found")
    caller_inspector = db.inspectors.get(user_id)
    if caller_inspector is not None and work_order.get("contractor_id") in (caller_inspector.get("excluded_contractor_ids") or []):
        raise errors.inspector_conflict()

    # Ownership (priority 10)
    if inspection.get("inspector_id") != user_id:
        raise errors.not_resource_owner()

    # Payload shape (priority 19)
    body = get_body()
    outcome = body.get("outcome")
    score_bps = body.get("score_bps")
    failure_reasons = body.get("failure_reasons")
    if outcome not in ("PASS", "FAIL"):
        raise errors.invalid_inspection_payload("outcome must be PASS or FAIL")
    try:
        score_int = int(score_bps)
    except (TypeError, ValueError):
        raise errors.invalid_inspection_payload("score_bps must be an integer")
    if score_int < 0 or score_int > 10000:
        raise errors.invalid_inspection_payload("score_bps must be in [0, 10000]")
    if outcome == "FAIL":
        if not isinstance(failure_reasons, list) or len(failure_reasons) == 0:
            raise errors.invalid_inspection_payload("failure_reasons must be non-empty when outcome is FAIL")
    else:  # PASS
        if failure_reasons is not None and isinstance(failure_reasons, list) and len(failure_reasons) > 0:
            raise errors.invalid_inspection_payload("failure_reasons must be empty when outcome is PASS")

    # Record
    inspection["outcome"] = outcome
    inspection["score_bps"] = score_int
    if outcome == "FAIL":
        inspection["failure_reasons"] = list(failure_reasons)
        inspection["remediation_required_by"] = db.format_dt(
            db.get_clock() + timedelta(days=core.REMEDIATION_WINDOW_DAYS)
        )
    else:
        inspection["failure_reasons"] = []
        inspection["remediation_required_by"] = None
    inspection["status"] = "RECORDED"
    db.touch(inspection)

    # Recompute contractor QA
    project = db.projects.get(inspection["project_id"])
    contractor = None
    if project is not None:
        contractor = db.contractors.get(project["contractor_id"])
    if contractor is not None:
        core.recompute_qa_score(contractor)

    if outcome == "PASS":
        # Project -> COMPLETED; finalize payment DRAFT -> AUTHORIZED.
        if project is not None:
            project["status"] = "COMPLETED"
            final_amount = core.compute_incentive(project, variant="FINAL")
            project["incentive_amount_cents"] = final_amount
            db.touch(project)

            payment = None
            for pay in db.payments.values():
                if pay.get("project_id") == project["id"] and pay.get("status") == "DRAFT":
                    payment = pay
                    break
            if payment is not None:
                payment["amount_cents"] = final_amount
                payment["reconciliation_delta_cents"] = final_amount - int(payment.get("amount_provisional_cents") or 0)
                payment["status"] = "AUTHORIZED"
                db.touch(payment)

            program = db.programs.get(project["program_id"])
            if program is not None:
                program["avoided_kwh_actual"] = int(program.get("avoided_kwh_actual") or 0) + int(
                    project.get("estimated_annual_kwh_savings") or 0
                )
                db.touch(program)
    else:  # FAIL
        if project is not None:
            project["status"] = "REMEDIATION"
            db.touch(project)
        if contractor is not None and int(contractor.get("qa_score_bps") or 0) < core.QA_SUSPENSION_THRESHOLD_BPS:
            core.suspend_contractor(contractor)

    return success_object(inspection)


@bp.post("/efficiency/inspections/<inspection_id>/void")
def void_inspection(inspection_id):
    require_roles({"ProgramManager"})
    inspection = fetch_or_404(db.inspections, inspection_id, "Inspection")
    if inspection["status"] != "SCHEDULED":
        raise errors.invalid_state(f"Inspection in {inspection['status']} cannot be voided")
    inspection["status"] = "VOID"
    db.touch(inspection)
    return success_object(inspection)
