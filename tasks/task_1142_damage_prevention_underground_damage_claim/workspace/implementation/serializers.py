"""Entity -> API payload serializers. System fields formatted per PRD §2.4."""

from util import fmt_dt


def _common(e):
    return {
        "id": e["id"],
        "created_at": fmt_dt(e["created_at"]),
        "updated_at": fmt_dt(e["updated_at"]),
        "version": e["version"],
    }


def excavator_out(e):
    out = _common(e)
    out.update({
        "company_name": e["company_name"],
        "contact_email": e["contact_email"],
        "program_status": e["program_status"],
        "offender_points": e["offender_points"],
        "credit_balance_cents": e["credit_balance_cents"],
        "total_outstanding_cents": e["total_outstanding_cents"],
    })
    return out


def locator_out(e):
    out = _common(e)
    out.update({
        "company_name": e["company_name"],
        "contact_email": e["contact_email"],
        "contract_region": e["contract_region"],
        "contract_status": e["contract_status"],
        "performance_score_bp": e["performance_score_bp"],
        "total_responses": e["total_responses"],
    })
    return out


def ticket_out(e):
    out = _common(e)
    out.update({
        "excavator_id": e["excavator_id"],
        "dig_site_address": e["dig_site_address"],
        "work_start_at": fmt_dt(e["work_start_at"]),
        "work_end_at": fmt_dt(e["work_end_at"]),
        "ticket_number": e["ticket_number"],
        "status": e["status"],
        "renewal_count": e["renewal_count"],
    })
    return out


def response_out(e):
    out = _common(e)
    out.update({
        "locate_ticket_id": e["locate_ticket_id"],
        "locator_id": e["locator_id"],
        "response_code": e["response_code"],
        "marks_completed_at": fmt_dt(e["marks_completed_at"]),
        "accuracy_verdict": e["accuracy_verdict"],
        "notes": e["notes"],
    })
    return out


def case_out(e):
    out = _common(e)
    out.update({
        "excavator_id": e["excavator_id"],
        "locate_ticket_id": e["locate_ticket_id"],
        "case_number": e["case_number"],
        "dig_site_address": e["dig_site_address"],
        "facility_type": e["facility_type"],
        "severity": e["severity"],
        "occurred_at": fmt_dt(e["occurred_at"]),
        "investigation_status": e["investigation_status"],
        "recovery_status": e["recovery_status"],
        "investigator_user_id": e["investigator_user_id"],
        "subtotal_cents": e["subtotal_cents"],
        "total_invoiced_cents": e["total_invoiced_cents"],
        "total_recovered_cents": e["total_recovered_cents"],
        "evidence_count": e["evidence_count"],
        "reconstruction_flags": list(e["reconstruction_flags"]),
    })
    return out


def evidence_out(e):
    # EvidenceItem carries only id + created_at (no updated_at, no version)
    return {
        "id": e["id"],
        "created_at": fmt_dt(e["created_at"]),
        "damage_case_id": e["damage_case_id"],
        "evidence_type": e["evidence_type"],
        "captured_at": fmt_dt(e["captured_at"]),
        "description": e["description"],
    }


def timeline_event_out(e):
    # TimelineEvent carries only id + created_at
    return {
        "id": e["id"],
        "created_at": fmt_dt(e["created_at"]),
        "damage_case_id": e["damage_case_id"],
        "event_kind": e["event_kind"],
        "event_at": fmt_dt(e["event_at"]),
        "source_ref_id": e["source_ref_id"],
        "flag": e["flag"],
    }


def allocation_out(e):
    out = _common(e)
    out.update({
        "damage_case_id": e["damage_case_id"],
        "supersedes_allocation_id": e["supersedes_allocation_id"],
        "root_cause_code": e["root_cause_code"],
        "basis": e["basis"],
        "shares": e["shares"],
        "status": e["status"],
        "revision_no": e["revision_no"],
        "proposed_at": fmt_dt(e["proposed_at"]) if e["proposed_at"] else None,
        "contest_deadline_at": fmt_dt(e["contest_deadline_at"]) if e["contest_deadline_at"] else None,
    })
    return out


def cost_line_out(e):
    out = _common(e)
    out.update({
        "damage_case_id": e["damage_case_id"],
        "category": e["category"],
        "description": e["description"],
        "quantity": e["quantity"],
        "unit_cost_cents": e["unit_cost_cents"],
        "line_total_cents": e["line_total_cents"],
    })
    return out


def invoice_out(e):
    out = _common(e)
    out.update({
        "damage_case_id": e["damage_case_id"],
        "fault_allocation_id": e["fault_allocation_id"],
        "debtor_type": e["debtor_type"],
        "debtor_id": e["debtor_id"],
        "status": e["status"],
        "invoiced_cents": e["invoiced_cents"],
        "standard_basis_cents": e["standard_basis_cents"],
        "amount_paid_cents": e["amount_paid_cents"],
        "amount_due_cents": e["amount_due_cents"],
        "issued_at": fmt_dt(e["issued_at"]) if e["issued_at"] else None,
        "due_at": fmt_dt(e["due_at"]) if e["due_at"] else None,
    })
    return out


def payment_out(e):
    out = _common(e)
    out.update({
        "payer_type": e["payer_type"],
        "payer_id": e["payer_id"],
        "amount_cents": e["amount_cents"],
        "claim_invoice_id": e["claim_invoice_id"],
        "status": e["status"],
        "allocations": e["allocations"],
        "applied_at": fmt_dt(e["applied_at"]),
    })
    return out


def dispute_out(e):
    out = _common(e)
    out.update({
        "target_type": e["target_type"],
        "target_id": e["target_id"],
        "reason": e["reason"],
        "detail": e["detail"],
        "filed_by_type": e["filed_by_type"],
        "filed_by_id": e["filed_by_id"],
        "status": e["status"],
        "rounds": e["rounds"],
        "response_deadline_at": fmt_dt(e["response_deadline_at"]),
    })
    return out


def subrogation_out(e):
    out = _common(e)
    out.update({
        "dispute_id": e["dispute_id"],
        "claim_invoice_id": e["claim_invoice_id"],
        "target_party_type": e["target_party_type"],
        "target_party_id": e["target_party_id"],
        "status": e["status"],
        "demand_amount_cents": e["demand_amount_cents"],
        "recovered_cents": e["recovered_cents"],
        "legal_cost_cents": e["legal_cost_cents"],
        "owner_share_cents": e["owner_share_cents"],
    })
    return out


def report_out(e):
    out = _common(e)
    out.update({
        "damage_case_id": e["damage_case_id"],
        "report_type": e["report_type"],
        "period_start": fmt_dt(e["period_start"]) if e["period_start"] else None,
        "period_end": fmt_dt(e["period_end"]) if e["period_end"] else None,
        "payload_notes": e["payload_notes"],
        "amends_report_id": e["amends_report_id"],
        "status": e["status"],
        "filed_at": fmt_dt(e["filed_at"]) if e["filed_at"] else None,
        "days_late": e["days_late"],
        "penalty_cents": e["penalty_cents"],
    })
    return out


def violation_out(e):
    out = _common(e)
    out.update({
        "excavator_id": e["excavator_id"],
        "damage_case_id": e["damage_case_id"],
        "points": e["points"],
        "effective_points": e["effective_points"],
        "status": e["status"],
    })
    return out


def course_out(e):
    out = _common(e)
    out.update({
        "course_code": e["course_code"],
        "title": e["title"],
        "required_for_status": e["required_for_status"],
        "credit_hours": e["credit_hours"],
    })
    return out


def assignment_out(e):
    out = _common(e)
    out.update({
        "excavator_id": e["excavator_id"],
        "course_id": e["course_id"],
        "status": e["status"],
        "due_at": fmt_dt(e["due_at"]),
        "completed_at": fmt_dt(e["completed_at"]) if e["completed_at"] else None,
    })
    return out
