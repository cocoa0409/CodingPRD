"""Lead endpoints."""

from __future__ import annotations

from flask import Blueprint, request

import db
import errors
from middleware import require_roles
from response import success_object
from routes.common import get_body, paginate, fetch_or_404, ref_or_404
from services import core

bp = Blueprint("leads", __name__)


@bp.post("/efficiency/leads")
def create_lead():
    require_roles({"ProgramManager"})
    body = get_body()
    customer = ref_or_404(db.customers, body.get("customer_id"), "Customer")
    program = ref_or_404(db.programs, body.get("program_id"), "Program")
    if program.get("status") != "ACTIVE":
        raise errors.program_not_active()
    lead = {
        "customer_id": customer["id"],
        "program_id": program["id"],
        "measure_type": body.get("measure_type"),
        "estimated_annual_kwh_savings": int(body.get("estimated_annual_kwh_savings") or 0),
        "source_channel": body.get("source_channel"),
        "assigned_contractor_id": None,
        "distribution_decision": None,
        "status": "NEW",
    }
    db.stamp_new(lead)
    db.leads[lead["id"]] = lead
    return success_object(lead, 201)


@bp.get("/efficiency/leads")
def list_leads():
    require_roles({"ProgramManager", "Contractor"})
    items = list(db.leads.values())
    status = request.args.get("status")
    program_id = request.args.get("program_id")
    contractor_id = request.args.get("contractor_id")
    customer_id = request.args.get("customer_id")
    assigned_contractor_id = request.args.get("assigned_contractor_id")
    if status is not None:
        items = [l for l in items if l.get("status") == status]
    if program_id is not None:
        items = [l for l in items if l.get("program_id") == program_id]
    if contractor_id is not None:
        items = [l for l in items if l.get("assigned_contractor_id") == contractor_id]
    if customer_id is not None:
        items = [l for l in items if l.get("customer_id") == customer_id]
    if assigned_contractor_id is not None:
        items = [l for l in items if l.get("assigned_contractor_id") == assigned_contractor_id]
    return paginate(items)


@bp.get("/efficiency/leads/<lead_id>")
def get_lead(lead_id):
    require_roles({"ProgramManager", "Contractor"})
    return success_object(fetch_or_404(db.leads, lead_id, "Lead"))


@bp.post("/efficiency/leads/<lead_id>/distribute")
def distribute_lead(lead_id):
    require_roles({"ProgramManager"})
    lead = fetch_or_404(db.leads, lead_id, "Lead")
    body = get_body()

    # State check first (priority 5)
    if lead["status"] != "NEW":
        raise errors.invalid_state(f"Lead in {lead['status']} cannot be distributed")

    # OCC (priority 6)
    expected = body.get("expected_lead_version")
    if expected is None:
        raise errors.stale_lead_version("expected_lead_version is required")
    if int(expected) != int(lead.get("version", 1)):
        raise errors.stale_lead_version()

    # Certification dimension screen (priority 8): fails specifically when no
    # APPROVED contractor carries an ACTIVE cert for this measure_type.
    if not core.any_contractor_with_measure_cert(lead.get("measure_type")):
        raise errors.certification_missing()

    # Program must be ACTIVE (priority 9)
    program = db.programs.get(lead["program_id"])
    if program is None or program.get("status") != "ACTIVE":
        raise errors.program_not_active()

    # Full eligibility (priority 12)
    candidates = core.eligible_contractors_for_lead(lead)
    if not candidates:
        raise errors.no_eligible_contractor()

    winner, ranking_key, tie_break_used = core.rank_candidates(candidates)
    lead["assigned_contractor_id"] = winner["id"]
    lead["distribution_decision"] = {
        "candidate_count": len(candidates),
        "ranking_key": ranking_key,
        "tie_break_used": tie_break_used,
    }
    lead["status"] = "OFFERED"
    db.touch(lead)
    return success_object(lead)


@bp.post("/efficiency/leads/<lead_id>/accept")
def accept_lead(lead_id):
    role, user_id = require_roles({"Contractor"})
    lead = fetch_or_404(db.leads, lead_id, "Lead")
    if lead["status"] != "OFFERED":
        raise errors.invalid_state(f"Lead in {lead['status']} cannot be accepted")
    # Ownership (priority 10)
    if lead.get("assigned_contractor_id") != user_id:
        raise errors.not_resource_owner()
    contractor = db.contractors.get(user_id)
    if contractor is None or contractor.get("status") != "APPROVED":
        raise errors.invalid_state("Contractor is not APPROVED")
    lead["status"] = "ACCEPTED"
    db.touch(lead)
    return success_object(lead)


@bp.post("/efficiency/leads/<lead_id>/expire")
def expire_lead(lead_id):
    require_roles({"ProgramManager"})
    lead = fetch_or_404(db.leads, lead_id, "Lead")
    if lead["status"] != "OFFERED":
        raise errors.invalid_state(f"Lead in {lead['status']} cannot be expired")
    lead["status"] = "EXPIRED"
    lead["assigned_contractor_id"] = None
    db.touch(lead)
    return success_object(lead)


@bp.post("/efficiency/leads/<lead_id>/withdraw")
def withdraw_lead(lead_id):
    require_roles({"ProgramManager"})
    lead = fetch_or_404(db.leads, lead_id, "Lead")
    if lead["status"] not in ("NEW", "OFFERED"):
        raise errors.invalid_state(f"Lead in {lead['status']} cannot be withdrawn")
    lead["status"] = "WITHDRAWN"
    lead["assigned_contractor_id"] = None
    db.touch(lead)
    return success_object(lead)
