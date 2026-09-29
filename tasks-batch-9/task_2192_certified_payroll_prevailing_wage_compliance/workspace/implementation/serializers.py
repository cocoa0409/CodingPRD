"""Row -> JSON projections. Field names mirror the entity tables exactly."""

from decimal import Decimal

import db


def num(value):
    """Hour quantities are emitted as JSON numbers carrying two decimal places."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    return value


def _common(row, out, versioned=True):
    out["id"] = row["id"]
    out["created_at"] = db.iso(row["created_at"])
    if versioned:
        out["updated_at"] = db.iso(row["updated_at"])
        out["version"] = row["version"]
    return out


def portal(row):
    out = {
        "portal_code": row["portal_code"],
        "submission_format": row["submission_format"],
        "cutoff_offset_days": row["cutoff_offset_days"],
        "grace_hours": row["grace_hours"],
        "requires_notarized_statement": row["requires_notarized_statement"],
    }
    return _common(row, out, versioned=False)


def determination(row):
    out = {
        "decision_number": row["decision_number"],
        "modification_number": row["modification_number"],
        "locality_code": row["locality_code"],
        "effective_date": db.iso(row["effective_date"]),
        "expiry_date": db.iso(row["expiry_date"]),
        "status": row["status"],
        "superseded_by_id": row["superseded_by_id"],
        "rate_count": row["rate_count"],
    }
    return _common(row, out)


def wage_rate(row):
    out = {
        "wage_determination_id": row["wage_determination_id"],
        "classification_code": row["classification_code"],
        "trade_code": row["trade_code"],
        "zone_code": row["zone_code"],
        "base_hourly_rate_cents": row["base_hourly_rate_cents"],
        "fringe_hourly_rate_cents": row["fringe_hourly_rate_cents"],
        "zone_adjustment_cents": row["zone_adjustment_cents"],
        "apprentice_scale_pct": list(row["apprentice_scale_pct"]),
    }
    return _common(row, out, versioned=False)


def contractor(row):
    out = {
        "legal_name": row["legal_name"],
        "parent_contractor_id": row["parent_contractor_id"],
        "dir_registration_number": row["dir_registration_number"],
        "registration_status": row["registration_status"],
        "debarment_status": row["debarment_status"],
        "debarment_risk_score": row["debarment_risk_score"],
        "last_finding_at": db.iso(row["last_finding_at"]),
        "open_critical_finding_count": row["open_critical_finding_count"],
        "outstanding_restitution_cents": row["outstanding_restitution_cents"],
    }
    return _common(row, out)


def staff(row):
    out = {
        "contractor_id": row["contractor_id"],
        "full_name": row["full_name"],
        "capability": row["capability"],
        "notary_reference_number": row["notary_reference_number"],
    }
    return _common(row, out, versioned=False)


def program(row):
    out = {
        "registration_number": row["registration_number"],
        "sponsor_name": row["sponsor_name"],
        "trade_code": row["trade_code"],
        "registration_status": row["registration_status"],
        "allowed_apprentice_hours_per_100_journey": row["allowed_apprentice_hours_per_100_journey"],
        "period_count": row["period_count"],
    }
    return _common(row, out)


def fringe_plan(row):
    out = {
        "contractor_id": row["contractor_id"],
        "plan_name": row["plan_name"],
        "plan_type": row["plan_type"],
        "annual_contribution_cents": row["annual_contribution_cents"],
        "annual_total_hours": num(row["annual_total_hours"]),
        "annual_public_works_hours": num(row["annual_public_works_hours"]),
        "approval_status": row["approval_status"],
        "annualized_credit_cents": row["annualized_credit_cents"],
        "claimed_credit_cents": row["claimed_credit_cents"],
    }
    return _common(row, out)


def project(row):
    out = {
        "project_name": row["project_name"],
        "awarding_agency": row["awarding_agency"],
        "locality_code": row["locality_code"],
        "zone_code": row["zone_code"],
        "wage_determination_id": row["wage_determination_id"],
        "reporting_portal_id": row["reporting_portal_id"],
        "funding_source": row["funding_source"],
        "contract_award_date": db.iso(row["contract_award_date"]),
        "status": row["status"],
        "posture": row["posture"],
        "open_finding_count": row["open_finding_count"],
        "open_critical_finding_count": row["open_critical_finding_count"],
        "outstanding_restitution_cents": row["outstanding_restitution_cents"],
        "suspended_assignment_count": row["suspended_assignment_count"],
    }
    return _common(row, out)


def assignment(row):
    out = {
        "project_id": row["project_id"],
        "contractor_id": row["contractor_id"],
        "upper_tier_assignment_id": row["upper_tier_assignment_id"],
        "tier": row["tier"],
        "subcontract_amount_cents": row["subcontract_amount_cents"],
        "status": row["status"],
        "cumulative_certified_hours": num(row["cumulative_certified_hours"]),
        "cumulative_restitution_cents": row["cumulative_restitution_cents"],
        "open_finding_count": row["open_finding_count"],
    }
    return _common(row, out)


def worker(row):
    out = {
        "employer_contractor_id": row["employer_contractor_id"],
        "worker_number": row["worker_number"],
        "full_name": row["full_name"],
        "default_classification_code": row["default_classification_code"],
        "apprentice_program_id": row["apprentice_program_id"],
        "apprentice_period": row["apprentice_period"],
        "interview_count": row["interview_count"],
    }
    return _common(row, out)


def submission(row):
    out = {
        "contract_assignment_id": row["contract_assignment_id"],
        "week_ending_date": db.iso(row["week_ending_date"]),
        "prepared_by_staff_id": row["prepared_by_staff_id"],
        "certified_by_staff_id": row["certified_by_staff_id"],
        "superseded_submission_id": row["superseded_submission_id"],
        "no_work_performed": row["no_work_performed"],
        "workflow_status": row["workflow_status"],
        "compliance_status": row["compliance_status"],
        "statement_signed_at": db.iso(row["statement_signed_at"]),
        "notary_reference_number": row["notary_reference_number"],
        "submitted_at": db.iso(row["submitted_at"]),
        "filing_due_at": db.iso(row["filing_due_at"]),
        "is_late": row["is_late"],
        "accepted_by_user_id": row["accepted_by_user_id"],
        "total_hours_reported": num(row["total_hours_reported"]),
        "straight_time_underpayment_cents": row["straight_time_underpayment_cents"],
        "make_whole_underpayment_cents": row["make_whole_underpayment_cents"],
        "excess_apprentice_hours": num(row["excess_apprentice_hours"]),
    }
    return _common(row, out)


def line(row):
    out = {
        "payroll_submission_id": row["payroll_submission_id"],
        "worker_id": row["worker_id"],
        "fringe_plan_id": row["fringe_plan_id"],
        "classification_code": row["classification_code"],
        "straight_hours": num(row["straight_hours"]),
        "overtime_hours": num(row["overtime_hours"]),
        "base_rate_paid_cents": row["base_rate_paid_cents"],
        "overtime_rate_paid_cents": row["overtime_rate_paid_cents"],
        "fringe_cash_paid_cents": row["fringe_cash_paid_cents"],
        "reported_as_apprentice": row["reported_as_apprentice"],
        "required_base_cents": row["required_base_cents"],
        "required_fringe_cents": row["required_fringe_cents"],
        "creditable_fringe_cents": row["creditable_fringe_cents"],
        "reclassified_journey_hours": num(row["reclassified_journey_hours"]),
        "line_underpayment_cents": row["line_underpayment_cents"],
    }
    return _common(row, out, versioned=False)


def interview(row):
    out = {
        "project_id": row["project_id"],
        "contract_assignment_id": row["contract_assignment_id"],
        "worker_id": row["worker_id"],
        "window_start": db.iso(row["window_start"]),
        "window_end": db.iso(row["window_end"]),
        "observed_classification_code": row["observed_classification_code"],
        "observed_hourly_rate_cents": row["observed_hourly_rate_cents"],
        "status": row["status"],
        "compared_submission_id": row["compared_submission_id"],
    }
    return _common(row, out)


def finding(row):
    out = {
        "project_id": row["project_id"],
        "payroll_submission_id": row["payroll_submission_id"],
        "worker_id": row["worker_id"],
        "source_interview_id": row["source_interview_id"],
        "finding_type": row["finding_type"],
        "severity": row["severity"],
        "restitution_required_cents": row["restitution_required_cents"],
        "restitution_outstanding_cents": row["restitution_outstanding_cents"],
        "status": row["status"],
        "response_round": row["response_round"],
        "raised_by_user_id": row["raised_by_user_id"],
        "response_due_at": db.iso(row["response_due_at"]),
        "response_narrative": row["response_narrative"],
    }
    return _common(row, out)


def payment(row):
    out = {
        "finding_id": row["finding_id"],
        "worker_id": row["worker_id"],
        "amount_cents": row["amount_cents"],
        "status": row["status"],
        "disbursed_at": db.iso(row["disbursed_at"]),
        "reversal_reason": row["reversal_reason"],
    }
    return _common(row, out)
