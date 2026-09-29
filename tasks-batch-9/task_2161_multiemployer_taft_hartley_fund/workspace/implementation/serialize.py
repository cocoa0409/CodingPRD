"""Resource serialisers. Field names come straight from SCAFFOLD section 1.1."""
from decimal import Decimal

import calc
from store import iso_ts


def num(value):
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    return value


def common(row, out):
    out["id"] = row["id"]
    out["created_at"] = iso_ts(row["created_at"])
    if "updated_at" in row:
        out["updated_at"] = iso_ts(row["updated_at"])
    if "version" in row:
        out["version"] = row["version"]
    return out


def fund(row):
    calc.recompute_fund_derived(row)
    out = {
        "name": row["name"],
        "ein": row["ein"],
        "fund_role": row["fund_role"],
        "plan_year_start_month": row["plan_year_start_month"],
        "interest_rate_annual_bps": row["interest_rate_annual_bps"],
        "ld_rate_bps": row["ld_rate_bps"],
        "ld_floor_cents": row["ld_floor_cents"],
        "grace_days": row["grace_days"],
        "hours_per_coverage_month": row["hours_per_coverage_month"],
        "bank_cap_hours": num(row["bank_cap_hours"]),
        "max_advance_coverage_months": row["max_advance_coverage_months"],
        "eligibility_lag_months": row["eligibility_lag_months"],
        "accrual_method": row["accrual_method"],
        "total_uvb_cents": row["total_uvb_cents"],
        "pool_prior_year_contributions_cents": list(row["pool_prior_year_contributions_cents"]),
        "allocated_uvb_cents": row["allocated_uvb_cents"],
        "unallocated_uvb_cents": row["unallocated_uvb_cents"],
        "reciprocity_agreement_status": row["reciprocity_agreement_status"],
        "active_union_trustees": row["active_union_trustees"],
        "active_employer_trustees": row["active_employer_trustees"],
        "governance_posture": row["governance_posture"],
        "suspended_employer_count": row["suspended_employer_count"],
        "reciprocal_receipts_cents": row["reciprocal_receipts_cents"],
        "collections_run_index": row["collections_run_index"],
    }
    return common(row, out)


def employer(row):
    out = {
        "fund_id": row["fund_id"],
        "legal_name": row["legal_name"],
        "ein": row["ein"],
        "contribution_rate_millicents_per_hour": row["contribution_rate_millicents_per_hour"],
        "controlled_group_parent_employer_id": row["controlled_group_parent_employer_id"],
        "prior_year_contributions_cents": list(row["prior_year_contributions_cents"]),
        "prior_year_base_units": list(row["prior_year_base_units"]),
        "status": row["status"],
        "delinquency_strikes": row["delinquency_strikes"],
        "cumulative_delinquent_cents": row["cumulative_delinquent_cents"],
    }
    return common(row, out)


def participant(row):
    out = {
        "fund_id": row["fund_id"],
        "full_name": row["full_name"],
        "ssn_last4": row["ssn_last4"],
        "credited_hours_total": num(row["credited_hours_total"]),
        "reciprocal_hours_total": num(row["reciprocal_hours_total"]),
        "hour_bank_hours": num(row["hour_bank_hours"]),
        "forfeited_hours_total": num(row["forfeited_hours_total"]),
        "coverage_through_month": row["coverage_through_month"],
        "eligibility_status": calc.eligibility_status(row),
        "vesting_service_years": row["vesting_service_years"],
        "total_pension_credits": num(row["total_pension_credits"]),
        "vested": row["vested"],
        "consecutive_break_years": row["consecutive_break_years"],
        "status": row["status"],
    }
    return common(row, out)


def report(row):
    out = {
        "employer_id": row["employer_id"],
        "work_period": row["work_period"],
        "amends_report_id": row["amends_report_id"],
        "origin": row["origin"],
        "due_date": row["due_date"],
        "total_hours_reported": num(row["total_hours_reported"]),
        "total_contributions_due_cents": row["total_contributions_due_cents"],
        "amount_remitted_cents": row["amount_remitted_cents"],
        "filing_status": row["filing_status"],
        "payment_status": row["payment_status"],
        "posted_at": iso_ts(row["posted_at"]) if row["posted_at"] else None,
        "paid_in_full_at": iso_ts(row["paid_in_full_at"]) if row["paid_in_full_at"] else None,
    }
    return common(row, out)


def line(row):
    out = {
        "report_id": row["report_id"],
        "participant_id": row["participant_id"],
        "hours": num(row["hours"]),
        "gross_wages_cents": row["gross_wages_cents"],
        "work_classification": row["work_classification"],
        "contribution_cents": row["contribution_cents"],
    }
    return common(row, out)


def assessment(row):
    out = {
        "report_id": row["report_id"],
        "basis": row["basis"],
        "assessed_on": row["assessed_on"],
        "days_late": row["days_late"],
        "principal_cents": row["principal_cents"],
        "interest_cents": row["interest_cents"],
        "liquidated_damages_cents": row["liquidated_damages_cents"],
        "total_cents": row["total_cents"],
        "status": row["status"],
        "settlement_amount_cents": row["settlement_amount_cents"],
        "waived_cents": row["waived_cents"],
    }
    return common(row, out)


def audit(row):
    findings = [
        {
            "participant_id": f["participant_id"],
            "work_period": f["work_period"],
            "unreported_hours": num(f["unreported_hours"]),
        }
        for f in row["findings"]
    ]
    out = {
        "employer_id": row["employer_id"],
        "auditor_user_id": row["auditor_user_id"],
        "period_start_month": row["period_start_month"],
        "period_end_month": row["period_end_month"],
        "findings": findings,
        "round_count": row["round_count"],
        "unreported_hours_found": num(row["unreported_hours_found"]),
        "underpayment_principal_cents": row["underpayment_principal_cents"],
        "resulting_report_id": row["resulting_report_id"],
        "status": row["status"],
    }
    return common(row, out)


def coverage_month(row):
    out = {
        "participant_id": row["participant_id"],
        "coverage_month": row["coverage_month"],
        "granting_report_id": row["granting_report_id"],
        "source": row["source"],
        "hours_applied": num(row["hours_applied"]),
        "status": row["status"],
    }
    return common(row, out)


def accrual(row):
    out = {
        "participant_id": row["participant_id"],
        "plan_year": row["plan_year"],
        "hours_credited": num(row["hours_credited"]),
        "reciprocal_hours_credited": num(row["reciprocal_hours_credited"]),
        "pension_credit": num(row["pension_credit"]),
        "vesting_year_earned": row["vesting_year_earned"],
        "break_in_service": row["break_in_service"],
        "accrual_status": row["accrual_status"],
    }
    return common(row, out)


def withdrawal(row):
    out = {
        "employer_id": row["employer_id"],
        "withdrawal_date": row["withdrawal_date"],
        "method": row["method"],
        "employer_share_fraction": num(row["employer_share_fraction"]),
        "raw_allocation_cents": row["raw_allocation_cents"],
        "de_minimis_reduction_cents": row["de_minimis_reduction_cents"],
        "net_liability_cents": row["net_liability_cents"],
        "annual_payment_cents": row["annual_payment_cents"],
        "schedule_years": row["schedule_years"],
        "twenty_year_cap_applied": row["twenty_year_cap_applied"],
        "capped_liability_cents": row["capped_liability_cents"],
        "accelerated_balance_cents": row["accelerated_balance_cents"],
        "certified_by_user_id": row["certified_by_user_id"],
        "demanded_on": row["demanded_on"],
        "review_grounds": row["review_grounds"],
        "status": row["status"],
    }
    return common(row, out)


def installment(row):
    out = {
        "assessment_id": row["assessment_id"],
        "installment_number": row["installment_number"],
        "due_date": row["due_date"],
        "amount_cents": row["amount_cents"],
        "status": row["status"],
        "paid_on": row["paid_on"],
    }
    return common(row, out)


def trustee(row):
    out = {
        "fund_id": row["fund_id"],
        "full_name": row["full_name"],
        "appointing_party": row["appointing_party"],
        "term_expires_on": row["term_expires_on"],
        "seat_status": row["seat_status"],
    }
    return common(row, out)


def motion(row):
    out = {
        "fund_id": row["fund_id"],
        "moved_by_trustee_id": row["moved_by_trustee_id"],
        "subject_type": row["subject_type"],
        "subject_ref_id": row["subject_ref_id"],
        "union_bloc_position": row["union_bloc_position"],
        "employer_bloc_position": row["employer_bloc_position"],
        "tallied_on": row["tallied_on"],
        "arbitration_award": row["arbitration_award"],
        "status": row["status"],
    }
    return common(row, out)


def vote(row):
    out = {
        "motion_id": row["motion_id"],
        "trustee_id": row["trustee_id"],
        "position": row["position"],
    }
    return common(row, out)


def transfer(row):
    out = {
        "participant_id": row["participant_id"],
        "sister_fund_id": row["sister_fund_id"],
        "transfer_type": row["transfer_type"],
        "work_period": row["work_period"],
        "hours": num(row["hours"]),
        "amount_cents": row["amount_cents"],
        "applied_coverage_months": row["applied_coverage_months"],
        "status": row["status"],
    }
    return common(row, out)
