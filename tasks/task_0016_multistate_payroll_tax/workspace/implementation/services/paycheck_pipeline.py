"""Paycheck withholding pipeline.

Computes gross + all withholdings + garnishment waterfall, in the order pinned
by PRD §3.4 / SCAFFOLD §1.3. Produces all derived fields on a Paycheck row and
the list of GarnishmentDeduction rows to attach.
"""
import db
from services import calculations as calc
from services import lookups
from services.calculations import (
    CCPA_MAX_BASIS_POINTS_CREDITOR_ONLY,
    CCPA_MAX_BASIS_POINTS_WITH_CHILD_SUPPORT,
)


def compute_paycheck_derived(paycheck):
    """Compute all derived fields on a Paycheck row in place.

    Does NOT mutate Employee YTD (that happens at PAID transition).
    Does NOT create GarnishmentDeduction rows — returns the deduction list so the
    caller can persist them atomically with the paycheck create.
    """
    employee = db.employees[paycheck["employee_id"]]
    run = db.paycheck_runs[paycheck["paycheck_run_id"]]
    pay_year = lookups.pay_date_year(run["pay_date"])

    # 1) Gross wages
    gross = calc.gross_wages(
        paycheck["pay_type"],
        paycheck["regular_hours_e2"],
        paycheck["overtime_hours_e2"],
        paycheck["double_hours_e2"],
        paycheck["retro_amount_cents"],
        paycheck["hourly_rate_cents"],
    )
    paycheck["gross_wages_cents"] = gross

    # 2) Federal — provisional
    w4 = lookups.effective_w4(employee["id"], pay_year)
    fed_table = lookups.find_tax_rate_table("FEDERAL", pay_year,
                                            w4["filing_status"] if w4 else "SINGLE")
    paycheck["fed_withheld_cents"] = calc.federal_withholding_provisional(
        gross, paycheck["pay_type"], w4, fed_table
    )

    # 3) State + 4) Local
    state_juris = lookups.state_jurisdiction(employee["work_state_code"])
    state_table = lookups.find_tax_rate_table(state_juris, pay_year, "SINGLE")
    paycheck["state_withheld_cents"] = calc.state_or_local_withholding(
        gross, paycheck["pay_type"], state_table, state_juris
    )

    local_juris = lookups.local_jurisdiction(employee.get("locality_code"))
    if local_juris is None:
        paycheck["local_withheld_cents"] = 0
    else:
        local_table = lookups.find_tax_rate_table(local_juris, pay_year, "SINGLE")
        paycheck["local_withheld_cents"] = calc.state_or_local_withholding(
            gross, paycheck["pay_type"], local_table, local_juris
        )

    # 5) Social Security
    paycheck["ss_withheld_cents"] = calc.fica_ss(gross, employee["ytd_ss_wages_cents"])

    # 6) Base Medicare
    paycheck["medicare_withheld_cents"] = calc.medicare_base(gross)

    # 7) Additional Medicare
    paycheck["addl_medicare_cents"] = calc.medicare_additional(
        gross, employee["ytd_medicare_wages_cents"]
    )

    # 8) Garnishment waterfall
    deductions = _garnishment_waterfall(paycheck)
    paycheck["garnishment_total_cents"] = sum(d["amount_cents"] for d in deductions)

    # 9) Net pay (floored at 0)
    total_with = (
        paycheck["fed_withheld_cents"]
        + paycheck["state_withheld_cents"]
        + paycheck["local_withheld_cents"]
        + paycheck["ss_withheld_cents"]
        + paycheck["medicare_withheld_cents"]
        + paycheck["addl_medicare_cents"]
        + paycheck["garnishment_total_cents"]
    )
    paycheck["net_pay_cents"] = max(0, gross - total_with)

    return deductions


def _garnishment_waterfall(paycheck):
    """SCAFFOLD §1.3 garnishment_waterfall + PRD §3.5.

    Pinned eval order: disposable_earnings -> paycheck_cap -> per-order min.
    Pinned rounding order: per-order amounts (already integer cents) summed last.
    Pinned tie-break: priority_rank ASC, served_on ASC, created_at ASC.
    """
    employee_id = paycheck["employee_id"]
    gross = paycheck["gross_wages_cents"]
    taxes = (
        paycheck["fed_withheld_cents"]
        + paycheck["state_withheld_cents"]
        + paycheck["local_withheld_cents"]
        + paycheck["ss_withheld_cents"]
        + paycheck["medicare_withheld_cents"]
        + paycheck["addl_medicare_cents"]
    )
    disposable_earnings = gross - taxes
    if disposable_earnings <= 0:
        return []

    # CCPA basis-points: 50% if any ACTIVE CHILD_SUPPORT; else 25%.
    has_cs = lookups.employee_has_active_child_support(employee_id)
    bp = CCPA_MAX_BASIS_POINTS_WITH_CHILD_SUPPORT if has_cs else CCPA_MAX_BASIS_POINTS_CREDITOR_ONLY
    paycheck_cap = (disposable_earnings * bp) // 10000

    # Candidate orders: ACTIVE only, for this employee.
    orders = [
        g for g in db.garnishment_orders.values()
        if g["employee_id"] == employee_id and g["status"] == "ACTIVE"
    ]
    orders.sort(key=lambda g: (g["priority_rank"], g["served_on"], g["created_at"]))

    remaining = paycheck_cap
    deductions = []
    for g in orders:
        if remaining <= 0:
            break
        per_order = min(g["weekly_cap_cents"], g["balance_remaining_cents"], remaining)
        if per_order > 0:
            deductions.append({
                "garnishment_order_id": g["id"],
                "amount_cents": per_order,
            })
            remaining -= per_order
    return deductions
