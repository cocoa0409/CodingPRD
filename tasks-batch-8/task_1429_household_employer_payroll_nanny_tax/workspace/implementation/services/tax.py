"""Tax liability accounts, safe-harbor deposits, filings, year-end (PRD 3.9-3.12)."""

from __future__ import annotations

from decimal import Decimal

import db
from services.posture import pack_for_state, issued_paychecks
from services.payroll import (
    FUTA_QUARTER_TRIGGER_CENTS,
    FUTA_RATE,
    FUTA_WAGE_BASE_CENTS,
    PERIODS_PER_YEAR,
)
from util import round_half_up_cents, round_half_up_4dp

TAX_TYPE_ORDER = ["FICA_EE", "FICA_ER", "FUTA_ER", "SIT_EE", "SUTA_ER"]

ESTIMATED_PAYMENT_THRESHOLD_CENTS = 100000
SAFE_HARBOR_PCT = Decimal("1.10")
UNDERPAYMENT_ACTUAL_PCT = Decimal("0.90")



def _account_lines(pc: dict) -> dict[str, int]:
    """Aggregate one paycheck's line arrays into account tax_type buckets."""
    out = {"FICA_EE": 0, "FICA_ER": 0, "FUTA_ER": 0, "SIT_EE": 0, "SUTA_ER": 0}
    for line in pc["withholding_lines"]:
        tt = line["tax_type"]
        if tt in ("SS_EE", "MEDICARE_EE", "ADDL_MEDICARE_EE"):
            out["FICA_EE"] += line["amount_cents"]
        elif tt == "SIT_EE":
            out["SIT_EE"] += line["amount_cents"]
        # FIT_EE has no liability account (it joins Schedule H directly)
    for line in pc["employer_tax_lines"]:
        tt = line["tax_type"]
        if tt in ("SS_ER", "MEDICARE_ER"):
            out["FICA_ER"] += line["amount_cents"]
        elif tt == "FUTA_ER":
            out["FUTA_ER"] += line["amount_cents"]
        elif tt == "SUTA_ER":
            out["SUTA_ER"] += line["amount_cents"]
    return out


def get_or_create_account(employer_id: str, tax_year: int, tax_type: str) -> dict:
    for acct in db.tax_accounts.values():
        if (acct["employer_id"] == employer_id and acct["tax_year"] == tax_year
                and acct["tax_type"] == tax_type):
            return acct
    acct = {
        "employer_id": employer_id,
        "tax_year": tax_year,
        "tax_type": tax_type,
        "accrued_cents": 0,
        "deposited_cents": 0,
        "penalty_cents": 0,
    }
    db.stamp_new(acct)
    db.tax_accounts[acct["id"]] = acct
    return acct


def ensure_year_accounts(employer_id: str, tax_year: int) -> list[dict]:
    """Lazily create all five accounts in the fixed order at finalize."""
    return [get_or_create_account(employer_id, tax_year, tt) for tt in TAX_TYPE_ORDER]


def accrue_paycheck(pay_run: dict, pc: dict, sign: int = 1) -> None:
    """Add (sign=+1 at finalize) or subtract (sign=-1 at void) a paycheck's
    line amounts from the year's TaxLiabilityAccount rows."""
    year = int(pay_run["pay_date"][:4])
    amounts = _account_lines(pc)
    for tax_type in TAX_TYPE_ORDER:
        acct = get_or_create_account(pay_run["employer_id"], year, tax_type)
        acct["accrued_cents"] += sign * amounts[tax_type]
        db.touch(acct)


def finalized_run_count(employer_id: str, tax_year: int) -> int:
    return sum(
        1
        for run in db.pay_runs.values()
        if run["employer_id"] == employer_id
        and run["status"] == "FINALIZED"
        and int(run["pay_date"][:4]) == tax_year
    )


def projected_annual(employer: dict, accrued: int, tax_year: int) -> int:
    """Forward-looking variant: accrued + per-period average x remaining
    periods. 0 before the first finalized paycheck of the year."""
    elapsed = finalized_run_count(employer["id"], tax_year)
    if elapsed == 0 or accrued == 0:
        return 0
    total_periods = PERIODS_PER_YEAR[employer["pay_frequency"]]
    per_period_avg = round_half_up_4dp(Decimal(accrued) / Decimal(max(1, elapsed)))
    remaining = total_periods - elapsed
    return round_half_up_cents(Decimal(accrued) + per_period_avg * Decimal(remaining))


def safe_harbor_figures(employer: dict, tax_year: int) -> tuple[int, int]:
    """Pinned six-step safe-harbor evaluation (PRD 3.9).

    Returns (annual_required, quarterly_installment).
    """
    fed_accrued = 0
    for tax_type in ("FICA_EE", "FICA_ER", "FUTA_ER"):
        for acct in db.tax_accounts.values():
            if (acct["employer_id"] == employer["id"] and acct["tax_year"] == tax_year
                    and acct["tax_type"] == tax_type):
                fed_accrued += acct["accrued_cents"]

    elapsed = finalized_run_count(employer["id"], tax_year)
    total_periods = PERIODS_PER_YEAR[employer["pay_frequency"]]
    per_period_avg = Decimal(fed_accrued) / Decimal(max(1, elapsed))
    projected = Decimal(fed_accrued) + per_period_avg * Decimal(total_periods - elapsed)

    prior = employer.get("prior_year_schedule_h_cents", 0)
    if prior > 0:
        prior_leg = Decimal(round_half_up_cents(SAFE_HARBOR_PCT * Decimal(prior)))
        cap = min(projected, prior_leg)
    else:
        cap = projected

    annual_required = cap if cap >= ESTIMATED_PAYMENT_THRESHOLD_CENTS else Decimal(0)
    installment = round_half_up_cents(annual_required / Decimal(4))
    return int(annual_required), installment


def deposited_total_for_year(employer_id: str, tax_year: int) -> int:
    return sum(
        dep["amount_cents"]
        for dep in db.deposits.values()
        if dep["employer_id"] == employer_id and dep["tax_year"] == tax_year
    )


def required_amount_for_quarter(employer: dict, tax_year: int, quarter: int) -> int:
    _, installment = safe_harbor_figures(employer, tax_year)
    deposited = deposited_total_for_year(employer["id"], tax_year)
    return max(0, installment * quarter - deposited)


def quarter_due_date(tax_year: int, quarter: int) -> str:
    if quarter == 1:
        return f"{tax_year}-04-15"
    if quarter == 2:
        return f"{tax_year}-06-15"
    if quarter == 3:
        return f"{tax_year}-09-15"
    return f"{tax_year + 1}-01-15"


def late_penalty(late_days: int, required_amount_cents: int) -> int:
    """Tiered penalty over the REQUIRED amount; boundaries exact."""
    if late_days <= 0:
        return 0
    if late_days <= 5:
        return round_half_up_cents(Decimal("0.02") * Decimal(required_amount_cents))
    if late_days <= 15:
        return round_half_up_cents(Decimal("0.05") * Decimal(required_amount_cents))
    return round_half_up_cents(Decimal("0.10") * Decimal(required_amount_cents))


def allocate_deposit(employer_id: str, tax_year: int, amount_cents: int) -> int:
    """Waterfall the deposit across the year's accounts in the fixed order,
    filling each deposited_cents up to its balance. Returns unapplied cents."""
    remaining = amount_cents
    for tax_type in TAX_TYPE_ORDER:
        acct = None
        for candidate in db.tax_accounts.values():
            if (candidate["employer_id"] == employer_id and candidate["tax_year"] == tax_year
                    and candidate["tax_type"] == tax_type):
                acct = candidate
                break
        if acct is None:
            continue
        balance = acct["accrued_cents"] + acct["penalty_cents"] - acct["deposited_cents"]
        fill = min(remaining, max(0, balance))
        if fill > 0:
            acct["deposited_cents"] += fill
            db.touch(acct)
            remaining -= fill
    return remaining


# ---------------------------------------------------------------------------
# Quarterly filing prepare figures
# ---------------------------------------------------------------------------

def _quarter_bounds(tax_year: int, quarter: int) -> tuple[str, str]:
    first_month = (quarter - 1) * 3 + 1
    start = f"{tax_year}-{first_month:02d}-01"
    if quarter == 4:
        end = f"{tax_year}-12-31"
    else:
        # Last day of the quarter's third month
        import calendar

        last_month = first_month + 2
        end = f"{tax_year}-{last_month:02d}-{calendar.monthrange(tax_year, last_month)[1]:02d}"
    return start, end


def prepare_figures(employer: dict, tax_year: int, quarter: int) -> dict:
    """Recompute filing amounts from the current ledger (PRD 3.10)."""
    q_start, q_end = _quarter_bounds(tax_year, quarter)
    checks = [
        pc for pc in issued_paychecks(employer["id"])
        if int(db.pay_runs[pc["pay_run_id"]]["pay_date"][:4]) == tax_year
    ]
    checks.sort(key=lambda pc: (db.pay_runs[pc["pay_run_id"]]["pay_date"], pc["created_at"]))

    def in_quarter(pc) -> bool:
        pay_date = db.pay_runs[pc["pay_run_id"]]["pay_date"]
        return q_start <= pay_date <= q_end

    quarter_wages = sum(pc["gross_cents"] for pc in checks if in_quarter(pc))
    futa_applies = quarter_wages >= FUTA_QUARTER_TRIGGER_CENTS
    year_applies = False
    for q in (1, 2, 3, 4):
        qs, qe = _quarter_bounds(tax_year, q)
        q_total = sum(
            pc["gross_cents"] for pc in checks
            if qs <= db.pay_runs[pc["pay_run_id"]]["pay_date"] <= qe
        )
        if q_total >= FUTA_QUARTER_TRIGGER_CENTS:
            year_applies = True

    # Chronological replay over per-worker remaining wage bases.
    futa_ytd: dict[str, int] = {}
    suta_ytd: dict[str, int] = {}
    futa_due = 0
    suta_due = 0
    for pc in checks:
        worker = db.workers.get(pc["worker_id"])
        pack = pack_for_state(worker["work_state_code"]) if worker else None
        gross = pc["gross_cents"]
        if year_applies:
            used = futa_ytd.get(pc["worker_id"], 0)
            base = min(gross, max(0, FUTA_WAGE_BASE_CENTS - used))
            futa_ytd[pc["worker_id"]] = used + base
            if in_quarter(pc):
                futa_due += round_half_up_cents(Decimal(base) * FUTA_RATE)
        if pack is not None:
            used_s = suta_ytd.get(pc["worker_id"], 0)
            sbase = min(gross, max(0, pack["suta_wage_base_cents"] - used_s))
            suta_ytd[pc["worker_id"]] = used_s + sbase
            if in_quarter(pc):
                from util import to_decimal_rate

                suta_due += round_half_up_cents(Decimal(sbase) * to_decimal_rate(pack["suta_rate"]))

    _, installment = safe_harbor_figures(employer, tax_year)
    return {
        "total_cash_wages_cents": quarter_wages,
        "futa_applies": futa_applies,
        "futa_due_cents": futa_due,
        "suta_due_cents": suta_due,
        "estimated_federal_payment_cents": installment,
    }


# ---------------------------------------------------------------------------
# Year-end Schedule H
# ---------------------------------------------------------------------------

def year_end_figures(employer: dict, tax_year: int) -> dict:
    accrued = {"FICA_EE": 0, "FICA_ER": 0, "FUTA_ER": 0}
    for acct in db.tax_accounts.values():
        if acct["employer_id"] == employer["id"] and acct["tax_year"] == tax_year:
            if acct["tax_type"] in accrued:
                accrued[acct["tax_type"]] = acct["accrued_cents"]

    checks = [
        pc for pc in issued_paychecks(employer["id"])
        if int(db.pay_runs[pc["pay_run_id"]]["pay_date"][:4]) == tax_year
    ]

    fit_total = 0
    per_worker: dict[str, dict] = {}
    for pc in checks:
        w = per_worker.setdefault(pc["worker_id"], {
            "worker_id": pc["worker_id"],
            "wages_cents": 0,
            "ss_wages_cents": 0,
            "ss_tax_cents": 0,
            "medicare_tax_cents": 0,
            "sit_cents": 0,
            "fit_cents": 0,
        })
        w["wages_cents"] += pc["gross_cents"]
        w["ss_wages_cents"] += pc.get("_ss_base_cents", 0)
        for line in pc["withholding_lines"]:
            tt = line["tax_type"]
            if tt == "SS_EE":
                w["ss_tax_cents"] += line["amount_cents"]
            elif tt in ("MEDICARE_EE", "ADDL_MEDICARE_EE"):
                w["medicare_tax_cents"] += line["amount_cents"]
            elif tt == "SIT_EE":
                w["sit_cents"] += line["amount_cents"]
            elif tt == "FIT_EE":
                w["fit_cents"] += line["amount_cents"]
                fit_total += line["amount_cents"]

    schedule_h_total = accrued["FICA_EE"] + accrued["FICA_ER"] + accrued["FUTA_ER"] + fit_total

    year_deposits = deposited_total_for_year(employer["id"], tax_year)
    leg_actual = round_half_up_cents(UNDERPAYMENT_ACTUAL_PCT * Decimal(schedule_h_total))
    prior = employer.get("prior_year_schedule_h_cents", 0)
    if prior > 0:
        leg_prior = round_half_up_cents(SAFE_HARBOR_PCT * Decimal(prior))
        threshold = min(leg_actual, leg_prior)
    else:
        threshold = leg_actual
    underpayment = year_deposits < threshold

    # Order W-2 lines by worker created_at ascending (insertion order breaks
    # the logical-clock ties) for determinism.
    def _worker_sort(line):
        worker = db.workers.get(line["worker_id"])
        return (worker["created_at"], worker["_seq"]) if worker else ("", 0)

    w2_lines = sorted(per_worker.values(), key=_worker_sort)
    return {
        "schedule_h_total_cents": schedule_h_total,
        "w2_lines": w2_lines,
        "underpayment_penalty_applies": underpayment,
    }
