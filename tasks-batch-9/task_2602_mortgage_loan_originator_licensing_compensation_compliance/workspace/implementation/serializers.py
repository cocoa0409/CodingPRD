"""Entity -> JSON projections. Field names come straight from the scaffold's
entity tables; timestamps render as ISO 8601 UTC with three fractional digits."""
from services import authority, calc
from util import fmt_dt


def _common(row):
    return {
        "created_at": fmt_dt(row["created_at"]),
        "updated_at": fmt_dt(row["updated_at"]),
        "version": row["version"],
    }


def originator(row):
    out = {
        "id": row["id"],
        "nmls_unique_id": row["nmls_unique_id"],
        "legal_name": row["legal_name"],
        "hire_date": fmt_dt(row["hire_date"]),
        "employment_status": row["employment_status"],
        "compensation_plan_id": row["compensation_plan_id"],
        "monitoring_status": row["monitoring_status"],
        "exposure_score": row["exposure_score"],
        "lifetime_accrued_cents": calc.lifetime_accrued_cents(row["id"]),
        "lifetime_clawed_back_cents": calc.lifetime_clawed_back_cents(row["id"]),
        "net_compensation_cents": calc.net_compensation_cents(row["id"]),
        "authorized_state_codes": authority.authorized_state_codes(row),
        "open_investigation_count": calc.open_investigation_count(row["id"]),
    }
    out.update(_common(row))
    return out


def license_registration(row):
    out = {
        "id": row["id"],
        "originator_id": row["originator_id"],
        "state_code": row["state_code"],
        "license_number": row["license_number"],
        "issue_date": fmt_dt(row["issue_date"]),
        "expiration_date": fmt_dt(row["expiration_date"]),
        "renewal_window_opens_at": fmt_dt(row["renewal_window_opens_at"]),
        "status": row["status"],
        "authority_effective_at": fmt_dt(row["authority_effective_at"]),
        "required_ce_hours": row["required_ce_hours"],
        "ce_hours_applied": row["ce_hours_applied"],
        "ce_reporting_year": row["ce_reporting_year"],
        "ce_satisfied": row["ce_satisfied"],
        "active_sponsoring_institution_code": row["active_sponsoring_institution_code"],
        "active_sponsorship_effective_at": fmt_dt(row["active_sponsorship_effective_at"]),
        "reinstatement_count": row["reinstatement_count"],
    }
    out.update(_common(row))
    return out


def sponsorship_transfer(row):
    out = {
        "id": row["id"],
        "license_registration_id": row["license_registration_id"],
        "sponsoring_institution_code": row["sponsoring_institution_code"],
        "effective_at": fmt_dt(row["effective_at"]),
        "relinquished_at": fmt_dt(row["relinquished_at"]),
        "status": row["status"],
        "superseded_by_created_at": fmt_dt(row["superseded_by_created_at"]),
    }
    out.update(_common(row))
    return out


def ce_course(row):
    out = {
        "id": row["id"],
        "course_code": row["course_code"],
        "credit_hours": row["credit_hours"],
        "category": row["category"],
        "approved_state_codes": list(row["approved_state_codes"]),
        "successive_year_blocked": row["successive_year_blocked"],
        "provider_status": row["provider_status"],
    }
    out.update(_common(row))
    return out


def ce_credit_record(row):
    out = {
        "id": row["id"],
        "originator_id": row["originator_id"],
        "ce_course_id": row["ce_course_id"],
        "completion_date": fmt_dt(row["completion_date"]),
        "reporting_period_year": row["reporting_period_year"],
        "is_makeup": row["is_makeup"],
        "credit_hours": row["credit_hours"],
        "category": row["category"],
        "attributed_year": row["attributed_year"],
        "credit_status": row["credit_status"],
        "void_reason": row["void_reason"],
    }
    out.update(_common(row))
    return out


def compensation_plan(row):
    out = {
        "id": row["id"],
        "plan_name": row["plan_name"],
        "drafted_by_user_id": row["drafted_by_user_id"],
        "approved_by_user_id": row["approved_by_user_id"],
        "base_basis_points": row["base_basis_points"],
        "min_fee_cents": row["min_fee_cents"],
        "max_fee_cents": row["max_fee_cents"],
        "salary_cents_per_period": row["salary_cents_per_period"],
        "volume_tier_enabled": row["volume_tier_enabled"],
        "concession_absorption_enabled": row["concession_absorption_enabled"],
        "status": row["status"],
        "prohibited_variable_count": row["prohibited_variable_count"],
        "assignment_effective_from": fmt_dt(row["assignment_effective_from"]),
        "assignment_effective_to": fmt_dt(row["assignment_effective_to"]),
        "assigned_originator_id": row["assigned_originator_id"],
    }
    out.update(_common(row))
    return out


def compensation_variable(row):
    out = {
        "id": row["id"],
        "compensation_plan_id": row["compensation_plan_id"],
        "variable_type": row["variable_type"],
        "permissibility": row["permissibility"],
        "weight_pct": row["weight_pct"],
        "justification_text": row["justification_text"],
    }
    out.update(_common(row))
    return out


def loan_application(row):
    out = {
        "id": row["id"],
        "originator_id": row["originator_id"],
        "compensation_plan_id": row["compensation_plan_id"],
        "state_code": row["state_code"],
        "borrower_reference": row["borrower_reference"],
        "application_taken_at": fmt_dt(row["application_taken_at"]),
        "product_type": row["product_type"],
        "requested_amount_cents": row["requested_amount_cents"],
        "par_rate_bps": row["par_rate_bps"],
        "note_rate_bps": row["note_rate_bps"],
        "locked_amount_cents": row["locked_amount_cents"],
        "funded_amount_cents": row["funded_amount_cents"],
        "funded_at": fmt_dt(row["funded_at"]),
        "payoff_date": fmt_dt(row["payoff_date"]),
        "lender_paid_comp_cents": row["lender_paid_comp_cents"],
        "borrower_paid_comp_cents": row["borrower_paid_comp_cents"],
        "file_quality_score": row["file_quality_score"],
        "hours_worked_pct": row["hours_worked_pct"],
        "status": row["status"],
        "compensation_status": row["compensation_status"],
        "authority_flag": row["authority_flag"],
        "closed_unit_index": row["closed_unit_index"],
    }
    out.update(_common(row))
    return out


def pricing_exception(row):
    out = {
        "id": row["id"],
        "loan_application_id": row["loan_application_id"],
        "requested_by_user_id": row["requested_by_user_id"],
        "requested_rate_bps": row["requested_rate_bps"],
        "concession_cents": row["concession_cents"],
        "reason_code": row["reason_code"],
        "justification_text": row["justification_text"],
        "status": row["status"],
        "requires_second_approval": row["requires_second_approval"],
        "decided_by_user_id": row["decided_by_user_id"],
        "second_decided_by_user_id": row["second_decided_by_user_id"],
        "decided_at": fmt_dt(row["decided_at"]),
        "decision_note": row["decision_note"],
        "comp_impact_cents": row["comp_impact_cents"],
    }
    out.update(_common(row))
    return out


def compensation_record(row):
    out = {
        "id": row["id"],
        "loan_application_id": row["loan_application_id"],
        "originator_id": row["originator_id"],
        "compensation_plan_id": row["compensation_plan_id"],
        "variant": row["variant"],
        "tier_bps_adder": row["tier_bps_adder"],
        "base_comp_cents": row["base_comp_cents"],
        "comp_impact_cents": row["comp_impact_cents"],
        "accrued_cents": row["accrued_cents"],
        "paid_cents": row["paid_cents"],
        "clawback_cents": row["clawback_cents"],
        "days_held": row["days_held"],
        "recapture_pct": row["recapture_pct"],
        "status": row["status"],
        "reconciled_at": fmt_dt(row["reconciled_at"]),
    }
    out.update(_common(row))
    return out


def advertisement(row):
    out = {
        "id": row["id"],
        "originator_id": row["originator_id"],
        "medium": row["medium"],
        "content_text": row["content_text"],
        "disclosed_nmls_ids": list(row["disclosed_nmls_ids"]),
        "disclosed_license_numbers": list(row["disclosed_license_numbers"]),
        "target_state_codes": list(row["target_state_codes"]),
        "status": row["status"],
        "disclosure_findings": list(row["disclosure_findings"]),
        "reviewed_by_user_id": row["reviewed_by_user_id"],
        "published_at": fmt_dt(row["published_at"]),
    }
    out.update(_common(row))
    return out


def examination_inquiry(row):
    out = {
        "id": row["id"],
        "originator_id": row["originator_id"],
        "state_code": row["state_code"],
        "exam_reference": row["exam_reference"],
        "opened_at": fmt_dt(row["opened_at"]),
        "response_due_at": fmt_dt(row["response_due_at"]),
        "status": row["status"],
        "response_round_count": row["response_round_count"],
        "last_response_at": fmt_dt(row["last_response_at"]),
        "escalation_reason": row["escalation_reason"],
    }
    out.update(_common(row))
    return out


def investigation(row):
    out = {
        "id": row["id"],
        "originator_id": row["originator_id"],
        "loan_application_id": row["loan_application_id"],
        "opened_by": row["opened_by"],
        "detected_at": fmt_dt(row["detected_at"]),
        "trigger_reason": row["trigger_reason"],
        "status": row["status"],
        "finding_by_user_id": row["finding_by_user_id"],
        "restitution_cents": row["restitution_cents"],
        "remediated_at": fmt_dt(row["remediated_at"]),
    }
    out.update(_common(row))
    return out


def audit_event(row):
    # AuditEvent deliberately carries no updated_at and no version.
    return {
        "id": row["id"],
        "subject_type": row["subject_type"],
        "subject_ref": row["subject_ref"],
        "event_type": row["event_type"],
        "actor_role": row["actor_role"],
        "actor_user_id": row["actor_user_id"],
        "detail": row["detail"],
        "sequence_no": row["sequence_no"],
        "created_at": fmt_dt(row["created_at"]),
    }
