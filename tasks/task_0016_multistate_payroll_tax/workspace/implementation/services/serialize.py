"""Serializers convert internal entity dicts (with datetime objects) to JSON-safe dicts."""
import db


def _common(entity, include_version=True):
    out = {
        "id": entity["id"],
        "created_at": db.iso8601(entity["created_at"]),
    }
    if include_version:
        out["updated_at"] = db.iso8601(entity["updated_at"])
        out["version"] = entity["version"]
    return out


def employee(e):
    out = _common(e)
    out.update({
        "full_name": e["full_name"],
        "work_state_code": e["work_state_code"],
        "residence_state_code": e["residence_state_code"],
        "locality_code": e.get("locality_code", "NONE"),
        "status": e["status"],
        "ytd_wages_cents": e["ytd_wages_cents"],
        "ytd_fed_withheld_cents": e["ytd_fed_withheld_cents"],
        "ytd_ss_wages_cents": e["ytd_ss_wages_cents"],
        "ytd_medicare_wages_cents": e["ytd_medicare_wages_cents"],
    })
    return out


def w4_form(w):
    out = _common(w)
    out.update({
        "employee_id": w["employee_id"],
        "tax_year": w["tax_year"],
        "filing_status": w["filing_status"],
        "dependents_amount_cents": w.get("dependents_amount_cents", 0),
        "other_income_cents": w.get("other_income_cents", 0),
        "deductions_cents": w.get("deductions_cents", 0),
        "extra_withholding_cents": w.get("extra_withholding_cents", 0),
        "supersedes_w4_id": w.get("supersedes_w4_id"),
        "status": w["status"],
        "filed_at": db.iso8601(w["filed_at"]) if w.get("filed_at") else None,
    })
    return out


def paycheck_run(r):
    out = _common(r)
    out.update({
        "pay_period_start": r["pay_period_start"],
        "pay_period_end": r["pay_period_end"],
        "pay_date": r["pay_date"],
        "prepared_by_user_id": r["prepared_by_user_id"],
        "approved_by_user_id": r.get("approved_by_user_id"),
        "status": r["status"],
        "total_gross_cents": r["total_gross_cents"],
    })
    return out


def paycheck(p):
    out = _common(p)
    out.update({
        "paycheck_run_id": p["paycheck_run_id"],
        "employee_id": p["employee_id"],
        "pay_type": p["pay_type"],
        "regular_hours_e2": p["regular_hours_e2"],
        "overtime_hours_e2": p["overtime_hours_e2"],
        "double_hours_e2": p["double_hours_e2"],
        "retro_amount_cents": p["retro_amount_cents"],
        "hourly_rate_cents": p["hourly_rate_cents"],
        "gross_wages_cents": p["gross_wages_cents"],
        "fed_withheld_cents": p["fed_withheld_cents"],
        "state_withheld_cents": p["state_withheld_cents"],
        "local_withheld_cents": p["local_withheld_cents"],
        "ss_withheld_cents": p["ss_withheld_cents"],
        "medicare_withheld_cents": p["medicare_withheld_cents"],
        "addl_medicare_cents": p["addl_medicare_cents"],
        "garnishment_total_cents": p["garnishment_total_cents"],
        "net_pay_cents": p["net_pay_cents"],
        "status": p["status"],
    })
    return out


def garnishment_order(g):
    out = _common(g)
    out.update({
        "employee_id": g["employee_id"],
        "order_type": g["order_type"],
        "priority_rank": g["priority_rank"],
        "weekly_cap_cents": g["weekly_cap_cents"],
        "original_balance_cents": g["original_balance_cents"],
        "balance_remaining_cents": g["balance_remaining_cents"],
        "status": g["status"],
        "served_on": g["served_on"],
    })
    return out


def garnishment_deduction(d):
    # GarnishmentDeduction has no updated_at / no version (PRD §2.4).
    return {
        "id": d["id"],
        "created_at": db.iso8601(d["created_at"]),
        "paycheck_id": d["paycheck_id"],
        "garnishment_order_id": d["garnishment_order_id"],
        "amount_cents": d["amount_cents"],
        "applied_at": db.iso8601(d["applied_at"]) if d.get("applied_at") else None,
    }


def remittance(r):
    out = _common(r)
    out.update({
        "period_month": r["period_month"],
        "jurisdiction": r["jurisdiction"],
        "tax_type": r["tax_type"],
        "accrued_cents": r["accrued_cents"],
        "reconciled_cents": r["reconciled_cents"],
        "paid_cents": r["paid_cents"],
        "status": r["status"],
    })
    return out


def tax_rate_table(t):
    # TaxRateTable has no updated_at / no version (PRD §2.4).
    return {
        "id": t["id"],
        "created_at": db.iso8601(t["created_at"]),
        "jurisdiction": t["jurisdiction"],
        "tax_year": t["tax_year"],
        "filing_status": t["filing_status"],
        "brackets_json": t["brackets_json"],
        "supplemental_flat_basis_points": t["supplemental_flat_basis_points"],
    }
