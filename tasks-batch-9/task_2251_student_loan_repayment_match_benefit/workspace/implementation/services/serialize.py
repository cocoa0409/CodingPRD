"""Resource serializers.

Ten collections are versioned resources and carry id/created_at/updated_at/
version. The four audit-row collections carry only id and created_at -- for
those, updated_at and version are absent from the payload entirely (PRD 2.4).
Derived fields are recomputed at read time so every rollup is reconciled in the
same response that moved it (PRD 2.8).
"""

import db
from services import calc


def _common(row):
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
    }


def _audit_common(row):
    return {"id": row["id"], "created_at": row["created_at"]}


# --------------------------------------------------------------------------

def plan_year(row):
    out = {
        "year": row["year"],
        "status": row["status"],
        "period_start": row["period_start"],
        "period_end": row["period_end"],
        "certification_window_open": row["certification_window_open"],
        "certification_deadline": row["certification_deadline"],
        "compensation_cap_cents": row["compensation_cap_cents"],
        "annual_deferral_limit_cents": row["annual_deferral_limit_cents"],
        "hce_prior_comp_threshold_cents": row["hce_prior_comp_threshold_cents"],
        "tier1_pct": row["tier1_pct"],
        "tier1_match_rate": row["tier1_match_rate"],
        "tier2_pct": row["tier2_pct"],
        "tier2_match_rate": row["tier2_match_rate"],
        "nondiscrimination_test_method": row["nondiscrimination_test_method"],
        "prior_year_nhce_acp": calc.as_float4(row["prior_year_nhce_acp"]),
        "unpaid_leave_day_cap": row["unpaid_leave_day_cap"],
        "leave_merge_buffer_days": row["leave_merge_buffer_days"],
        "total_deferral_match_funded_cents":
            calc.plan_year_total_deferral_match_funded(row["id"]),
        "total_qslp_match_funded_cents":
            calc.plan_year_total_qslp_match_funded(row["id"]),
        "forfeiture_balance_cents":
            calc.plan_year_forfeiture_balance(row["id"]),
        "accepted_certification_count":
            calc.plan_year_accepted_certification_count(row["id"]),
        "true_up_completed": row["true_up_completed"],
        "reopened_count": row["reopened_count"],
    }
    out.update(_common(row))
    return out


def plan_amendment(row):
    out = {
        "plan_year_id": row["plan_year_id"],
        "document_ref": row["document_ref"],
        "effective_date": row["effective_date"],
        "status": row["status"],
        "adopted_at": row["adopted_at"],
        "notice_sent_at": row["notice_sent_at"],
        "effective_at": row["effective_at"],
        "notice_channel": row["notice_channel"],
        "rescinded_reason": row["rescinded_reason"],
    }
    out.update(_common(row))
    return out


def refresh_employee(row):
    """PRD 3.2 -- the employee returns from LEAVE_UNPAID to ACTIVE on its own:
    once the logical clock has advanced strictly past the end_date of every
    UNPAID leave of that employee, the next read observes ACTIVE."""
    if row["employment_status"] != "LEAVE_UNPAID":
        return
    clock = db.now()
    unpaid = [e for e in db.rows("leave_events")
              if e["employee_id"] == row["id"] and e["leave_type"] == "UNPAID"]
    if not unpaid:
        return
    if all(clock > e["_end_dt"] for e in unpaid):
        row["employment_status"] = "ACTIVE"
        db.touch(row)


def employee(row):
    refresh_employee(row)
    py = calc.open_plan_year()
    py_id = py["id"] if py else None
    out = {
        "external_id": row["external_id"],
        "hire_date": row["hire_date"],
        "prior_year_compensation_cents": row["prior_year_compensation_cents"],
        "vesting_service_months": row["vesting_service_months"],
        "employment_status": row["employment_status"],
        "termination_date": row["termination_date"],
        "rehire_date": row["rehire_date"],
        "hce_flag": calc.hce_flag_against(row, py),
        "ytd_eligible_compensation_cents":
            calc.ytd_eligible_compensation(row["id"], py_id) if py else 0,
        "ytd_deferral_cents":
            calc.ytd_deferral(row["id"], py_id) if py else 0,
        "ytd_deferral_match_cents":
            calc.ytd_deferral_match(row["id"], py_id) if py else 0,
        "ytd_qslp_match_cents":
            calc.ytd_qslp_match(row["id"], py_id) if py else 0,
        "remaining_qslp_space_cents": calc.remaining_qslp_space(row["id"]),
        "vested_pct": float(calc.vested_pct(row["vesting_service_months"])),
        "unpaid_leave_days_ytd": calc.unpaid_leave_days_ytd(row["id"], py),
    }
    out.update(_common(row))
    return out


def leave_event(row):
    out = {
        "employee_id": row["employee_id"],
        "leave_type": row["leave_type"],
        "start_date": row["start_date"],
        "end_date": row["end_date"],
        "day_count": row["day_count"],
    }
    out.update(_audit_common(row))
    return out


def payroll_period(row):
    out = {
        "plan_year_id": row["plan_year_id"],
        "period_number": row["period_number"],
        "start_date": row["start_date"],
        "end_date": row["end_date"],
        "pay_date": row["pay_date"],
        "status": row["status"],
        "reopen_count": row["reopen_count"],
        "total_eligible_compensation_cents":
            calc.period_total_eligible_compensation(row),
        "total_deferral_match_cents": calc.period_total_deferral_match(row),
    }
    out.update(_common(row))
    return out


def contribution_record(row):
    out = {
        "employee_id": row["employee_id"],
        "payroll_period_id": row["payroll_period_id"],
        "eligible_compensation_cents": row["eligible_compensation_cents"],
        "elective_deferral_cents": row["elective_deferral_cents"],
        "counted_compensation_cents": row["counted_compensation_cents"],
        "deferral_match_cents": row["deferral_match_cents"],
        "qslp_space_tier1_cents": row["qslp_space_tier1_cents"],
        "qslp_space_tier2_cents": row["qslp_space_tier2_cents"],
    }
    out.update(_common(row))
    return out


def loan_account(row):
    out = {
        "employee_id": row["employee_id"],
        "servicer_name": row["servicer_name"],
        "account_last4": row["account_last4"],
        "original_principal_cents": row["original_principal_cents"],
        "status": row["status"],
        "evidence_ref": row["evidence_ref"],
    }
    out.update(_common(row))
    return out


def loan_certification(row):
    out = {
        "employee_id": row["employee_id"],
        "plan_year_id": row["plan_year_id"],
        "supersedes_certification_id": row["supersedes_certification_id"],
        "certification_method": row["certification_method"],
        "status": row["status"],
        "submitted_at": row["submitted_at"],
        "decided_at": row["decided_at"],
        "accepted_by_user_id": row["accepted_by_user_id"],
        "return_count": row["return_count"],
        "certified_total_cents": calc.certified_total(row),
        "eligible_total_cents": row["eligible_total_cents"],
        "matched_total_cents": calc.matched_total(row),
        "unmatched_eligible_cents": calc.unmatched_eligible(row),
        "capped_by_statutory_room": row["capped_by_statutory_room"],
        "audit_hold_reason": row["audit_hold_reason"],
        "void_reason": row["void_reason"],
    }
    out.update(_common(row))
    return out


def certification_line(row):
    out = {
        "certification_id": row["certification_id"],
        "loan_account_id": row["loan_account_id"],
        "payment_date": row["payment_date"],
        "amount_cents": row["amount_cents"],
        "covered_period_start": row["covered_period_start"],
        "covered_period_end": row["covered_period_end"],
    }
    out.update(_audit_common(row))
    return out


def match_allocation(row):
    out = {
        "employee_id": row["employee_id"],
        "plan_year_id": row["plan_year_id"],
        "certification_id": row["certification_id"],
        "payroll_period_id": row["payroll_period_id"],
        "funding_batch_id": row["funding_batch_id"],
        "allocation_type": row["allocation_type"],
        "amount_cents": row["amount_cents"],
        "tier1_applied_cents": row["tier1_applied_cents"],
        "tier2_applied_cents": row["tier2_applied_cents"],
        "funding_status": row["funding_status"],
        "vesting_status": row["vesting_status"],
        "vested_cents": row["vested_cents"],
        "forfeited_cents": row["forfeited_cents"],
    }
    out.update(_common(row))
    return out


def funding_batch(row):
    out = {
        "plan_year_id": row["plan_year_id"],
        "payroll_period_id": row["payroll_period_id"],
        "status": row["status"],
        "total_allocated_cents": calc.batch_total_allocated(row),
        "allocation_count": calc.batch_allocation_count(row),
        "forfeiture_offset_cents": calc.batch_forfeiture_offset(row),
        "net_funding_cents": calc.batch_net_funding(row),
        "transmitted_at": row["transmitted_at"],
        "settled_at": row["settled_at"],
        "rejection_code": row["rejection_code"],
        "retransmit_count": row["retransmit_count"],
    }
    out.update(_common(row))
    return out


def forfeiture_record(row):
    out = {
        "match_allocation_id": row["match_allocation_id"],
        "employee_id": row["employee_id"],
        "plan_year_id": row["plan_year_id"],
        "amount_cents": row["amount_cents"],
        "reason_code": row["reason_code"],
    }
    out.update(_audit_common(row))
    return out


def correction_adjustment(row):
    out = {
        "match_allocation_id": row["match_allocation_id"],
        "employee_id": row["employee_id"],
        "plan_year_id": row["plan_year_id"],
        "nondiscrimination_test_id": row["nondiscrimination_test_id"],
        "reason_code": row["reason_code"],
        "amount_cents": row["amount_cents"],
        "created_by_user_id": row["created_by_user_id"],
        "note": row["note"],
    }
    out.update(_audit_common(row))
    return out


def nondiscrimination_test(row):
    out = {
        "plan_year_id": row["plan_year_id"],
        "test_method": row["test_method"],
        "include_qslp_match": row["include_qslp_match"],
        "status": row["status"],
        "hce_acp": calc.as_float4(row["hce_acp"]),
        "nhce_acp": calc.as_float4(row["nhce_acp"]),
        "limit_acp": calc.as_float4(row["limit_acp"]),
        "hce_count": row["hce_count"],
        "nhce_count": row["nhce_count"],
        "computed_at": row["computed_at"],
        "correction_method": row["correction_method"],
        "total_correction_cents": sum(
            a["amount_cents"] for a in db.rows("correction_adjustments")
            if a["nondiscrimination_test_id"] == row["id"]),
    }
    out.update(_common(row))
    return out
