"""Entity representations. Derived fields are computed at render time."""
from decimal import Decimal

import db
from services import derive
from services.numbers import num_out


def _common(row, out):
    out["id"] = row["id"]
    out["created_at"] = row["created_at"]
    if "version" in row:
        out["updated_at"] = row["updated_at"]
        out["version"] = row["version"]
    return out


def _n(value):
    if isinstance(value, Decimal):
        return num_out(value)
    return value


def state_rule(row):
    out = {
        "state_code": row["state_code"],
        "min_weekly_salary_cents": row["min_weekly_salary_cents"],
        "hce_annual_cents": row["hce_annual_cents"],
        "duties_test_variant": row["duties_test_variant"],
        "computer_exemption_recognized": row["computer_exemption_recognized"],
        "outside_sales_recognized": row["outside_sales_recognized"],
        "hce_shortcut_recognized": row["hce_shortcut_recognized"],
        "ic_test": row["ic_test"],
        "liquidated_damages_multiplier": _n(row["liquidated_damages_multiplier"]),
        "reclass_notice_days": row["reclass_notice_days"],
        "back_wage_lookback_weeks_override": row["back_wage_lookback_weeks_override"],
    }
    return _common(row, out)


def audit_project(row):
    view = derive.project_view(row)
    out = {
        "name": row["name"],
        "fiscal_year": row["fiscal_year"],
        "lookback_policy": row["lookback_policy"],
        "status": row["status"],
        "remediation_posture": view["remediation_posture"],
        "open_misclassified_headcount": view["open_misclassified_headcount"],
        "total_back_wage_exposure_cents": view["total_back_wage_exposure_cents"],
        "converted_annual_payroll_delta_cents": view[
            "converted_annual_payroll_delta_cents"
        ],
        "committed_correction_cents": view["committed_correction_cents"],
    }
    return _common(row, out)


def job_family(row):
    view = derive.family_view(row)
    out = {
        "audit_project_id": row["audit_project_id"],
        "parent_family_id": row["parent_family_id"],
        "name": row["name"],
        "code": row["code"],
        "risk_variant": view["risk_variant"],
        "risk_score": view["risk_score"],
        "risk_tier": view["risk_tier"],
        "family_headcount": view["family_headcount"],
        "open_misclassified_count": view["open_misclassified_count"],
        "remediation_priority_rank": row["remediation_priority_rank"],
    }
    return _common(row, out)


def position(row):
    view = derive.position_view(row)
    out = {
        "job_family_id": row["job_family_id"],
        "title": row["title"],
        "job_code": row["job_code"],
        "current_fls_status": row["current_fls_status"],
        "claimed_exemption_test": row["claimed_exemption_test"],
        "annual_salary_cents": row["annual_salary_cents"],
        "salary_basis": row["salary_basis"],
        "work_state_code": row["work_state_code"],
        "incumbent_count": row["incumbent_count"],
        "avg_weekly_hours": _n(row["avg_weekly_hours"]),
        "requires_advanced_degree": row["requires_advanced_degree"],
        "works_primarily_offsite": row["works_primarily_offsite"],
        "weekly_salary_cents": view["weekly_salary_cents"],
        "self_reported_exempt_pct_override": _n(
            row["self_reported_exempt_pct_override"]
        ),
        "self_reported_exempt_pct": _n(view["self_reported_exempt_pct"]),
        "primary_duty_pct": _n(view["primary_duty_pct"]),
        "validated_weekly_hours": _n(view["validated_weekly_hours"]),
        "corroborated_supervises_headcount": view["corroborated_supervises_headcount"],
        "corroborated_hire_fire_influence": view["corroborated_hire_fire_influence"],
        "duties_validation_status": view["duties_validation_status"],
        "classification_status": row["classification_status"],
        "overtime_eligible": view["overtime_eligible"],
    }
    return _common(row, out)


def duty_statement(row):
    out = {
        "position_id": row["position_id"],
        "duty_code": row["duty_code"],
        "description": row["description"],
        "claimed_time_pct": _n(row["claimed_time_pct"]),
        "is_exempt_duty": row["is_exempt_duty"],
        "discretion_level": row["discretion_level"],
    }
    return _common(row, out)


def interview(row):
    out = {
        "position_id": row["position_id"],
        "respondent_type": row["respondent_type"],
        "respondent_ref": row["respondent_ref"],
        "interviewer_user_id": row["interviewer_user_id"],
        "scheduled_start_at": row["scheduled_start_at"],
        "scheduled_end_at": row["scheduled_end_at"],
        "reported_exempt_duty_pct": _n(row["reported_exempt_duty_pct"]),
        "reported_weekly_hours": _n(row["reported_weekly_hours"]),
        "supervises_headcount": row["supervises_headcount"],
        "has_hire_fire_influence": row["has_hire_fire_influence"],
        "completed_at": row["completed_at"],
        "attested_at": row["attested_at"],
        "void_reason": row["void_reason"],
        "status": row["status"],
    }
    return _common(row, out)


def exemption_analysis(row):
    out = {
        "position_id": row["position_id"],
        "applied_test": row["applied_test"],
        "analyst_user_id": row["analyst_user_id"],
        "reviewer_user_id": row["reviewer_user_id"],
        "revision_round": row["revision_round"],
        "weekly_salary_cents_snapshot": row["weekly_salary_cents_snapshot"],
        "primary_duty_pct_snapshot": _n(row["primary_duty_pct_snapshot"]),
        "applicable_salary_floor_cents": row["applicable_salary_floor_cents"],
        "applicable_duty_floor_pct": _n(row["applicable_duty_floor_pct"]),
        "salary_threshold_source": row["salary_threshold_source"],
        "federal_pass": row["federal_pass"],
        "state_pass": row["state_pass"],
        "hce_shortcut_applied": row["hce_shortcut_applied"],
        "outcome": row["outcome"],
        "return_reason": row["return_reason"],
        "status": row["status"],
    }
    return _common(row, out)


def reclassification_case(row):
    out = {
        "position_id": row["position_id"],
        "effective_date": row["effective_date"],
        "effective_end_date": row["effective_end_date"],
        "conversion_method": row["conversion_method"],
        "expected_weekly_hours": _n(row["expected_weekly_hours"]),
        "converted_hourly_rate_cents": row["converted_hourly_rate_cents"],
        "projected_annual_cost_cents": row["projected_annual_cost_cents"],
        "cost_delta_cents": row["cost_delta_cents"],
        "notice_channel": row["notice_channel"],
        "notice_sent_at": row["notice_sent_at"],
        "acknowledged_at": row["acknowledged_at"],
        "acknowledged_by_ref": row["acknowledged_by_ref"],
        "escalation_reason": row["escalation_reason"],
        "exposure_cents": derive.case_exposure_cents(row),
        "pay_conversion_status": row["pay_conversion_status"],
        "communication_status": row["communication_status"],
        "case_status": derive.case_status(row),
    }
    return _common(row, out)


def back_wage_estimate(row):
    out = {
        "reclassification_case_id": row["reclassification_case_id"],
        "method": row["method"],
        "lookback_weeks": row["lookback_weeks"],
        "weekly_ot_hours": _n(row["weekly_ot_hours"]),
        "week_ot_cents": row["week_ot_cents"],
        "gross_exposure_cents": row["gross_exposure_cents"],
        "liquidated_damages_cents": row["liquidated_damages_cents"],
        "total_exposure_cents": row["total_exposure_cents"],
        "status": row["status"],
    }
    return _common(row, out)


def voluntary_correction(row):
    out = {
        "reclassification_case_id": row["reclassification_case_id"],
        "decision": row["decision"],
        "proposed_amount_cents": row["proposed_amount_cents"],
        "proposed_by_user_id": row["proposed_by_user_id"],
        "approved_amount_cents": row["approved_amount_cents"],
        "approver_user_id": row["approver_user_id"],
        "rejection_reason": row["rejection_reason"],
        "status": row["status"],
    }
    return _common(row, out)


def contractor_review(row):
    out = {
        "audit_project_id": row["audit_project_id"],
        "vendor_name": row["vendor_name"],
        "engagement_state_code": row["engagement_state_code"],
        "free_from_control": row["free_from_control"],
        "outside_usual_course": row["outside_usual_course"],
        "independent_trade": row["independent_trade"],
        "economic_reality_factors": row["economic_reality_factors"],
        "behavioral_control_score": row["behavioral_control_score"],
        "financial_control_score": row["financial_control_score"],
        "relationship_score": row["relationship_score"],
        "applied_ic_test": row["applied_ic_test"],
        "ic_score": row["ic_score"],
        "outcome": row["outcome"],
        "status": row["status"],
    }
    return _common(row, out)


def job_change_trigger(row):
    out = {
        "position_id": row["position_id"],
        "trigger_type": row["trigger_type"],
        "new_annual_salary_cents": row["new_annual_salary_cents"],
        "new_exempt_duty_pct": _n(row["new_exempt_duty_pct"]),
        "new_supervises_headcount": row["new_supervises_headcount"],
        "new_work_state_code": row["new_work_state_code"],
        "requires_reanalysis": row["requires_reanalysis"],
        "reason_code": row["reason_code"],
    }
    return _common(row, out)


def paginate(rows, limit, offset, serializer):
    total = len(rows)
    window = rows[offset : offset + limit]
    return [serializer(r) for r in window], total


__all__ = [
    "state_rule",
    "audit_project",
    "job_family",
    "position",
    "duty_statement",
    "interview",
    "exemption_analysis",
    "reclassification_case",
    "back_wage_estimate",
    "voluntary_correction",
    "contractor_review",
    "job_change_trigger",
    "paginate",
    "db",
]
