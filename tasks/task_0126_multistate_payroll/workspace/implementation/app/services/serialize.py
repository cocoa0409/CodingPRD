"""Resource serialization — convert internal dicts to API response shapes."""
from __future__ import annotations

from typing import Any


def serialize_employee(emp: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": emp["id"],
        "full_name": emp["full_name"],
        "hire_date": emp["hire_date"],
        "work_state": emp["work_state"],
        "work_locality": emp["work_locality"],
        "hourly_rate_cents": emp["hourly_rate_cents"],
        "ytd_gross_wages_cents": emp["ytd_gross_wages_cents"],
        "ytd_social_security_wages_cents": emp["ytd_social_security_wages_cents"],
        "ytd_medicare_wages_cents": emp["ytd_medicare_wages_cents"],
        "status": emp["status"],
        "termination_date": emp.get("termination_date"),
        "created_at": emp["created_at"],
        "updated_at": emp["updated_at"],
        "version": emp["version"],
    }


def serialize_w4(w4: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": w4["id"],
        "employee_id": w4["employee_id"],
        "filing_status": w4["filing_status"],
        "dependents_amount_cents": w4["dependents_amount_cents"],
        "other_income_cents": w4["other_income_cents"],
        "additional_withholding_cents": w4["additional_withholding_cents"],
        "state_allowances": w4["state_allowances"],
        "prefilled_from_prior_year": w4["prefilled_from_prior_year"],
        "effective_pay_period_id": w4["effective_pay_period_id"],
        "created_at": w4["created_at"],
        "updated_at": w4["updated_at"],
        "version": w4["version"],
    }


def serialize_pay_period(pp: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": pp["id"],
        "period_start": pp["period_start"],
        "period_end": pp["period_end"],
        "pay_date": pp["pay_date"],
        "status": pp["status"],
        "paycheck_count": pp["paycheck_count"],
        "created_at": pp["created_at"],
        "updated_at": pp["updated_at"],
        "version": pp["version"],
    }


def serialize_payroll_item(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": item["id"],
        "pay_period_id": item["pay_period_id"],
        "employee_id": item["employee_id"],
        "regular_hours": item["regular_hours"],
        "overtime_hours": item["overtime_hours"],
        "double_hours": item["double_hours"],
        "retro_adjustment_cents": item["retro_adjustment_cents"],
        "locked": item["locked"],
        "created_at": item["created_at"],
        "updated_at": item["updated_at"],
        "version": item["version"],
    }


def serialize_paycheck(pc: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": pc["id"],
        "pay_period_id": pc["pay_period_id"],
        "payroll_item_id": pc["payroll_item_id"],
        "employee_id": pc["employee_id"],
        "w4_profile_id": pc.get("w4_profile_id"),
        "gross_wages_cents": pc.get("gross_wages_cents"),
        "federal_withholding_cents": pc.get("federal_withholding_cents"),
        "state_withholding_cents": pc.get("state_withholding_cents"),
        "local_withholding_cents": pc.get("local_withholding_cents"),
        "social_security_cents": pc.get("social_security_cents"),
        "medicare_base_cents": pc.get("medicare_base_cents"),
        "medicare_additional_cents": pc.get("medicare_additional_cents"),
        "garnishment_total_cents": pc.get("garnishment_total_cents", 0),
        "net_pay_cents": pc.get("net_pay_cents"),
        "is_retro_correction": pc.get("is_retro_correction", False),
        "correction_of_paycheck_id": pc.get("correction_of_paycheck_id"),
        "status": pc["status"],
        "created_at": pc["created_at"],
        "updated_at": pc["updated_at"],
        "version": pc["version"],
    }


def serialize_garnishment(g: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": g["id"],
        "employee_id": g["employee_id"],
        "order_type": g["order_type"],
        "priority_rank": g["priority_rank"],
        "total_owed_cents": g["total_owed_cents"],
        "amount_collected_cents": g["amount_collected_cents"],
        "cap_pct_of_disposable": g["cap_pct_of_disposable"],
        "effective_pay_date": g["effective_pay_date"],
        "status": g["status"],
        "created_at": g["created_at"],
        "updated_at": g["updated_at"],
        "version": g["version"],
    }


def serialize_remittance(r: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": r["id"],
        "tax_year": r["tax_year"],
        "tax_month": r["tax_month"],
        "total_federal_withholding_cents": r["total_federal_withholding_cents"],
        "total_state_withholding_cents": r["total_state_withholding_cents"],
        "total_local_withholding_cents": r["total_local_withholding_cents"],
        "total_social_security_cents": r["total_social_security_cents"],
        "total_medicare_cents": r["total_medicare_cents"],
        "total_medicare_additional_cents": r["total_medicare_additional_cents"],
        "state_breakdown": r["state_breakdown"],
        "status": r["status"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


def serialize_tax_bracket(t: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": t["id"],
        "jurisdiction": t["jurisdiction"],
        "filing_status": t["filing_status"],
        "tax_year": t["tax_year"],
        "brackets": t["brackets"],
        "created_at": t["created_at"],
    }


def serialize_ytd_ledger(e: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": e["id"],
        "employee_id": e["employee_id"],
        "paycheck_id": e["paycheck_id"],
        "tax_year": e["tax_year"],
        "gross_wages_delta_cents": e["gross_wages_delta_cents"],
        "social_security_wages_delta_cents": e["social_security_wages_delta_cents"],
        "medicare_wages_delta_cents": e["medicare_wages_delta_cents"],
        "entry_kind": e["entry_kind"],
        "created_at": e["created_at"],
    }
