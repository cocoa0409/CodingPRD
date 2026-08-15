"""Serializers: project internal entity dicts to their public shape.

Computed fields (employer compliance_posture, worker YTD/leave fields, tax
account projected/balance) are derived fresh at serialization time so they
always reflect the current ledger and logical clock.
"""

from __future__ import annotations

import db
from services import tax as tax_svc
from services.payroll import (
    FICA_COVERAGE_THRESHOLD_CENTS,
    worker_cash_wages_ytd,
    worker_futa_wages_ytd,
    worker_ss_wages_ytd,
)
from services.posture import compute_posture

LEAVE_ACCRUAL_DIVISOR = 30
LEAVE_ANNUAL_CAP_MINUTES = 2400


def serialize_employer(e: dict) -> dict:
    return {
        "id": e["id"],
        "legal_name": e["legal_name"],
        "primary_state_code": e["primary_state_code"],
        "fein": e["fein"],
        "pay_frequency": e["pay_frequency"],
        "prior_year_schedule_h_cents": e["prior_year_schedule_h_cents"],
        "status": e["status"],
        "compliance_posture": compute_posture(e),
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
    }


def serialize_state_rule_pack(p: dict) -> dict:
    return {
        "id": p["id"],
        "state_code": p["state_code"],
        "min_pay_frequency": p["min_pay_frequency"],
        "weekly_ot_threshold_minutes": p["weekly_ot_threshold_minutes"],
        "daily_ot_threshold_minutes": p["daily_ot_threshold_minutes"],
        "daily_dt_threshold_minutes": p["daily_dt_threshold_minutes"],
        "live_in_weekly_ot_eligible": p["live_in_weekly_ot_eligible"],
        "live_in_daily_ot_eligible": p["live_in_daily_ot_eligible"],
        "min_wage_cents": p["min_wage_cents"],
        "sit_rate": p["sit_rate"],
        "suta_rate": p["suta_rate"],
        "suta_wage_base_cents": p["suta_wage_base_cents"],
        "workers_comp_required": p["workers_comp_required"],
        "new_hire_report_days": p["new_hire_report_days"],
        "pay_stub_required": p["pay_stub_required"],
        "created_at": p["created_at"],
    }


def serialize_registration(r: dict) -> dict:
    return {
        "id": r["id"],
        "employer_id": r["employer_id"],
        "state_code": r["state_code"],
        "agency": r["agency"],
        "agency_account_number": r["agency_account_number"],
        "status": r["status"],
        "submitted_at": r["submitted_at"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def serialize_worker(w: dict) -> dict:
    year = db.clock_year()
    cash_ytd = worker_cash_wages_ytd(w["id"], year)
    ytd_approved = sum(
        ts["total_worked_minutes"]
        for ts in db.timesheets.values()
        if ts["worker_id"] == w["id"]
        and ts["status"] in ("APPROVED", "LOCKED")
        and int(ts["period_start"][:4]) == year
    )
    accrued = min(ytd_approved // LEAVE_ACCRUAL_DIVISOR, LEAVE_ANNUAL_CAP_MINUTES)
    used = sum(
        lr["requested_minutes"]
        for lr in db.leave_requests.values()
        if lr["worker_id"] == w["id"] and lr["status"] == "APPROVED"
    )
    return {
        "id": w["id"],
        "employer_id": w["employer_id"],
        "full_name": w["full_name"],
        "ssn": w["ssn"],
        "work_state_code": w["work_state_code"],
        "hire_date": w["hire_date"],
        "work_arrangement": w["work_arrangement"],
        "classification": w["classification"],
        "classification_answers": w["classification_answers"],
        "status": w["status"],
        "new_hire_report_date": w["new_hire_report_date"],
        "termination_date": w["termination_date"],
        "cash_wages_ytd_cents": cash_ytd,
        "fica_covered": cash_ytd >= FICA_COVERAGE_THRESHOLD_CENTS,
        "ss_wages_paid_ytd_cents": worker_ss_wages_ytd(w["id"], year),
        "futa_wages_ytd_cents": worker_futa_wages_ytd(w["id"], year),
        "ytd_approved_minutes": ytd_approved,
        "accrued_leave_minutes": accrued,
        "used_leave_minutes": used,
        "available_leave_minutes": accrued - used,
        "created_at": w["created_at"],
        "updated_at": w["updated_at"],
        "version": w["version"],
    }


def serialize_agreement(a: dict) -> dict:
    return {
        "id": a["id"],
        "worker_id": a["worker_id"],
        "hourly_rate_cents": a["hourly_rate_cents"],
        "pay_method": a["pay_method"],
        "guaranteed_minutes_per_week": a["guaranteed_minutes_per_week"],
        "fit_withholding_cents_per_period": a["fit_withholding_cents_per_period"],
        "effective_from": a["effective_from"],
        "effective_to": a["effective_to"],
        "status": a["status"],
        "superseded_by_id": a["superseded_by_id"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def serialize_timesheet(t: dict) -> dict:
    return {
        "id": t["id"],
        "worker_id": t["worker_id"],
        "pay_run_id": t["pay_run_id"],
        "period_start": t["period_start"],
        "period_end": t["period_end"],
        "entries": t["entries"],
        "total_worked_minutes": t["total_worked_minutes"],
        "status": t["status"],
        "submitted_at": t["submitted_at"],
        "created_at": t["created_at"],
        "updated_at": t["updated_at"],
        "version": t["version"],
    }


def serialize_pay_run(r: dict) -> dict:
    return {
        "id": r["id"],
        "employer_id": r["employer_id"],
        "period_start": r["period_start"],
        "period_end": r["period_end"],
        "pay_date": r["pay_date"],
        "status": r["status"],
        "recalc_status": r["recalc_status"],
        "total_gross_cents": r["total_gross_cents"],
        "total_net_cents": r["total_net_cents"],
        "total_employer_tax_cents": r["total_employer_tax_cents"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def serialize_paycheck(p: dict) -> dict:
    return {
        "id": p["id"],
        "pay_run_id": p["pay_run_id"],
        "worker_id": p["worker_id"],
        "basis": p["basis"],
        "basis_stale": p["basis_stale"],
        "pay_method": p["pay_method"],
        "regular_minutes": p["regular_minutes"],
        "overtime_minutes": p["overtime_minutes"],
        "double_minutes": p["double_minutes"],
        "guarantee_top_up_minutes": p["guarantee_top_up_minutes"],
        "fww_effective_rate_cents_per_minute": p["fww_effective_rate_cents_per_minute"],
        "provisional_gross_cents": p["provisional_gross_cents"],
        "gross_cents": p["gross_cents"],
        "withholding_lines": p["withholding_lines"],
        "employer_tax_lines": p["employer_tax_lines"],
        "net_pay_cents": p["net_pay_cents"],
        "status": p["status"],
        "deposit_status": p["deposit_status"],
        "stub_status": p["stub_status"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def serialize_leave_request(lr: dict) -> dict:
    return {
        "id": lr["id"],
        "worker_id": lr["worker_id"],
        "start_date": lr["start_date"],
        "end_date": lr["end_date"],
        "requested_minutes": lr["requested_minutes"],
        "status": lr["status"],
        "created_at": lr["created_at"],
        "updated_at": lr["updated_at"],
        "version": lr["version"],
    }


def serialize_tax_account(a: dict) -> dict:
    employer = db.employers.get(a["employer_id"])
    projected = tax_svc.projected_annual(employer, a["accrued_cents"], a["tax_year"]) if employer else 0
    return {
        "id": a["id"],
        "employer_id": a["employer_id"],
        "tax_year": a["tax_year"],
        "tax_type": a["tax_type"],
        "accrued_cents": a["accrued_cents"],
        "projected_annual_cents": projected,
        "deposited_cents": a["deposited_cents"],
        "penalty_cents": a["penalty_cents"],
        "balance_cents": a["accrued_cents"] + a["penalty_cents"] - a["deposited_cents"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def serialize_deposit(d: dict) -> dict:
    return {
        "id": d["id"],
        "employer_id": d["employer_id"],
        "tax_year": d["tax_year"],
        "quarter": d["quarter"],
        "amount_cents": d["amount_cents"],
        "remitted_on": d["remitted_on"],
        "required_amount_cents": d["required_amount_cents"],
        "due_date": d["due_date"],
        "late_days": d["late_days"],
        "penalty_cents": d["penalty_cents"],
        "unapplied_cents": d["unapplied_cents"],
        "created_at": d["created_at"],
    }


def serialize_filing(f: dict) -> dict:
    return {
        "id": f["id"],
        "employer_id": f["employer_id"],
        "tax_year": f["tax_year"],
        "quarter": f["quarter"],
        "status": f["status"],
        "total_cash_wages_cents": f["total_cash_wages_cents"],
        "futa_applies": f["futa_applies"],
        "futa_due_cents": f["futa_due_cents"],
        "suta_due_cents": f["suta_due_cents"],
        "estimated_federal_payment_cents": f["estimated_federal_payment_cents"],
        "prepared_by_user_id": f["prepared_by_user_id"],
        "prepared_at": f["prepared_at"],
        "created_at": f["created_at"],
        "updated_at": f["updated_at"],
        "version": f["version"],
    }


def serialize_policy(p: dict) -> dict:
    return {
        "id": p["id"],
        "employer_id": p["employer_id"],
        "state_code": p["state_code"],
        "policy_number": p["policy_number"],
        "coverage_start": p["coverage_start"],
        "coverage_end": p["coverage_end"],
        "status": p["status"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def serialize_year_end_package(p: dict) -> dict:
    return {
        "id": p["id"],
        "employer_id": p["employer_id"],
        "tax_year": p["tax_year"],
        "status": p["status"],
        "schedule_h_total_cents": p["schedule_h_total_cents"],
        "w2_lines": p["w2_lines"],
        "underpayment_penalty_applies": p["underpayment_penalty_applies"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }
