"""Paycheck gross-to-net calculations (PRD 3.6, 3.8).

Money is integer cents; durations integer minutes; every rounding point is
pinned (round half-up). rate_per_minute is an exact integer because agreement
creation enforces hourly_rate_cents % 60 == 0.
"""

from __future__ import annotations

from decimal import Decimal

import db
from services.posture import pack_for_state
from util import round_half_up_cents, round_half_up_4dp, to_decimal_rate

# Calculation constants (SCAFFOLD 1.3)
SS_RATE = Decimal("0.062")
MEDICARE_RATE = Decimal("0.0145")
ADDL_MEDICARE_RATE = Decimal("0.009")
ADDL_MEDICARE_THRESHOLD_CENTS = 20000000
SS_WAGE_BASE_CENTS = 17610000
FUTA_RATE = Decimal("0.006")
FUTA_WAGE_BASE_CENTS = 700000
FUTA_QUARTER_TRIGGER_CENTS = 100000
FICA_COVERAGE_THRESHOLD_CENTS = 280000

WEEKS_PER_PERIOD = {"WEEKLY": 1, "BIWEEKLY": 2, "SEMIMONTHLY": 2, "MONTHLY": 4}
PERIODS_PER_YEAR = {"WEEKLY": 52, "BIWEEKLY": 26, "SEMIMONTHLY": 24, "MONTHLY": 12}


# ---------------------------------------------------------------------------
# Worker YTD derivations (per calendar year of the paycheck pay_dates)
# ---------------------------------------------------------------------------

def worker_issued_checks(worker_id: str, year: int) -> list[dict]:
    """ISSUED paychecks of the worker with pay_date in the given year,
    ordered pay_date ASC then created_at ASC."""
    out = []
    for pc in db.paychecks.values():
        if pc["worker_id"] != worker_id or pc["status"] != "ISSUED":
            continue
        run = db.pay_runs.get(pc["pay_run_id"])
        if run is None:
            continue
        if int(run["pay_date"][:4]) != year:
            continue
        out.append(pc)
    out.sort(key=lambda pc: (db.pay_runs[pc["pay_run_id"]]["pay_date"], pc["created_at"], pc["_seq"]))
    return out


def worker_cash_wages_ytd(worker_id: str, year: int) -> int:
    return sum(pc["gross_cents"] for pc in worker_issued_checks(worker_id, year))


def worker_ss_wages_ytd(worker_id: str, year: int) -> int:
    return sum(pc.get("_ss_base_cents", 0) for pc in worker_issued_checks(worker_id, year))


def worker_fica_wages_ytd(worker_id: str, year: int) -> int:
    return sum(pc.get("_fica_base_cents", 0) for pc in worker_issued_checks(worker_id, year))


def worker_futa_wages_ytd(worker_id: str, year: int) -> int:
    return sum(pc.get("_futa_base_cents", 0) for pc in worker_issued_checks(worker_id, year))


def worker_suta_wages_ytd(worker_id: str, year: int) -> int:
    return sum(pc.get("_suta_base_cents", 0) for pc in worker_issued_checks(worker_id, year))


def employer_quarter_applies_futa(employer_id: str, year: int, extra_wages: int = 0,
                                  extra_pay_date: str | None = None) -> bool:
    """FUTA accrues for the whole year once any quarter's household cash wages
    reach the 100000-cent trigger (boundary exact: >=). At pay-run calculate
    time the run's own member gross is projected into its quarter via
    extra_wages/extra_pay_date; once projected-in, FUTA accrues for the year."""
    from services.posture import issued_paychecks

    quarter_totals = {1: 0, 2: 0, 3: 0, 4: 0}
    for pc in issued_paychecks(employer_id):
        run = db.pay_runs.get(pc["pay_run_id"])
        if run is None:
            continue
        pay_date = run["pay_date"]
        if int(pay_date[:4]) != year:
            continue
        month = int(pay_date[5:7])
        quarter = (month - 1) // 3 + 1
        quarter_totals[quarter] += pc["gross_cents"]
    if extra_pay_date is not None and int(extra_pay_date[:4]) == year:
        extra_quarter = (int(extra_pay_date[5:7]) - 1) // 3 + 1
        quarter_totals[extra_quarter] += extra_wages
    return any(total >= FUTA_QUARTER_TRIGGER_CENTS for total in quarter_totals.values())


# ---------------------------------------------------------------------------
# Coverage helpers
# ---------------------------------------------------------------------------

def agreement_covering(worker_id: str, date_str: str) -> dict | None:
    """ACTIVE agreement whose [effective_from, effective_to] covers date_str.
    Most recently created wins when several qualify."""
    best = None
    for ag in db.agreements.values():
        if ag["worker_id"] != worker_id or ag["status"] != "ACTIVE":
            continue
        if ag["effective_from"] > date_str:
            continue
        if ag["effective_to"] is not None and ag["effective_to"] < date_str:
            continue
        if best is None or ag["_seq"] > best["_seq"]:
            best = ag
    return best


def agreement_covers_period(worker_id: str, period_start: str, period_end: str) -> dict | None:
    """ACTIVE agreement covering every day of the half-open [start, end)."""
    from datetime import datetime, timedelta

    last_day = (datetime.strptime(period_end, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")
    for ag in db.agreements.values():
        if ag["worker_id"] != worker_id or ag["status"] != "ACTIVE":
            continue
        if ag["effective_from"] <= period_start and (
            ag["effective_to"] is None or ag["effective_to"] >= last_day
        ):
            return ag
    return None


def covering_timesheet(worker_id: str, period_start: str, period_end: str) -> dict | None:
    """The APPROVED-or-LOCKED timesheet exactly covering the period. An
    APPROVED one (fresher data) wins over a LOCKED one."""
    approved = None
    locked = None
    for ts in db.timesheets.values():
        if ts["worker_id"] != worker_id:
            continue
        if ts["period_start"] != period_start or ts["period_end"] != period_end:
            continue
        if ts["status"] == "APPROVED":
            if approved is None or ts["_seq"] > approved["_seq"]:
                approved = ts
        elif ts["status"] == "LOCKED":
            if locked is None or ts["_seq"] > locked["_seq"]:
                locked = ts
    return approved or locked


# ---------------------------------------------------------------------------
# Gross pay
# ---------------------------------------------------------------------------

def _gross_hourly(entries, rate_per_minute: int, guaranteed_period_minutes: int,
                  pack: dict, work_arrangement: str, basis: str) -> dict:
    """Hourly gross with pinned daily-then-weekly OT extraction (PRD 3.6)."""
    provisional = rate_per_minute * guaranteed_period_minutes
    if basis == "GUARANTEE_FALLBACK":
        return {
            "regular_minutes": guaranteed_period_minutes,
            "overtime_minutes": 0,
            "double_minutes": 0,
            "guarantee_top_up_minutes": 0,
            "fww_effective_rate_cents_per_minute": None,
            "provisional_gross_cents": provisional,
            "gross_cents": rate_per_minute * guaranteed_period_minutes,
        }

    live_in = work_arrangement == "LIVE_IN"
    daily_ok = (not live_in) or pack["live_in_daily_ot_eligible"]
    weekly_ok = (not live_in) or pack["live_in_weekly_ot_eligible"]
    daily_ot = pack["daily_ot_threshold_minutes"]
    daily_dt = pack["daily_dt_threshold_minutes"]

    regular = 0
    ot = 0
    dt = 0
    total_worked = 0
    # Stage 1: daily extraction
    if daily_ok:
        for entry in entries:
            worked = entry["worked_minutes"]
            total_worked += worked
            day_dt = max(0, worked - daily_dt) if daily_dt > 0 else 0
            if daily_ot > 0:
                upper = worked if daily_dt <= 0 else min(worked, daily_dt)
                day_ot = max(0, upper - daily_ot)
            else:
                day_ot = 0
            dt += day_dt
            ot += day_ot
            regular += worked - day_ot - day_dt
    else:
        for entry in entries:
            total_worked += entry["worked_minutes"]
        regular = total_worked

    # Stage 2: weekly extraction over post-daily regular minutes
    if weekly_ok:
        weekly_ot = max(0, regular - pack["weekly_ot_threshold_minutes"])
        regular -= weekly_ot
        ot += weekly_ot

    # Stage 3: guarantee top-up (straight time, excluded from OT bases)
    top_up = max(0, guaranteed_period_minutes - total_worked)

    ot_rate = round_half_up_cents(Decimal(rate_per_minute) * Decimal(3) / Decimal(2))
    gross = rate_per_minute * (regular + top_up) + ot_rate * ot + rate_per_minute * 2 * dt
    return {
        "regular_minutes": regular,
        "overtime_minutes": ot,
        "double_minutes": dt,
        "guarantee_top_up_minutes": top_up,
        "fww_effective_rate_cents_per_minute": None,
        "provisional_gross_cents": provisional,
        "gross_cents": gross,
    }


def _gross_fww(entries, rate_per_minute: int, guaranteed_minutes_per_week: int,
               weeks_in_period: int, pack: dict, work_arrangement: str, basis: str) -> dict:
    """Fluctuating-workweek gross: pinned total -> rate(4dp) -> premium order."""
    weekly_guarantee_pay = guaranteed_minutes_per_week * rate_per_minute
    guarantee_pay_period = weekly_guarantee_pay * weeks_in_period
    provisional = guarantee_pay_period

    if basis == "TIMESHEET":
        total_worked = sum(e["worked_minutes"] for e in entries)
    else:
        total_worked = guaranteed_minutes_per_week * weeks_in_period

    live_in = work_arrangement == "LIVE_IN"
    weekly_ok = (not live_in) or pack["live_in_weekly_ot_eligible"]
    ot_minutes = max(0, total_worked - pack["weekly_ot_threshold_minutes"]) if weekly_ok else 0

    if total_worked > 0:
        eff_rate = round_half_up_4dp(Decimal(guarantee_pay_period) / Decimal(total_worked))
    else:
        eff_rate = Decimal("0.0000")
    premium = round_half_up_cents(Decimal("0.5") * eff_rate * Decimal(ot_minutes))
    gross = guarantee_pay_period + premium

    guaranteed_period_minutes = guaranteed_minutes_per_week * weeks_in_period
    return {
        "regular_minutes": total_worked - ot_minutes,
        "overtime_minutes": ot_minutes,
        "double_minutes": 0,
        "guarantee_top_up_minutes": max(0, guaranteed_period_minutes - total_worked),
        "fww_effective_rate_cents_per_minute": float(eff_rate),
        "provisional_gross_cents": provisional,
        "gross_cents": gross,
    }


# ---------------------------------------------------------------------------
# Withholding and employer tax lines
# ---------------------------------------------------------------------------

def _line(tax_type: str, amount: int) -> dict | None:
    """Zero-amount lines are omitted from the lines arrays."""
    if amount == 0:
        return None
    return {"tax_type": tax_type, "amount_cents": amount}


def compute_gross_fields(pay_run: dict, worker: dict, agreement: dict) -> dict:
    """Phase 1 of calculate: basis + minutes + gross figures (no tax lines)."""
    pack = pack_for_state(worker["work_state_code"])
    frequency = db.employers[pay_run["employer_id"]]["pay_frequency"]
    weeks = WEEKS_PER_PERIOD[frequency]
    rate_per_minute = agreement["hourly_rate_cents"] // 60
    guaranteed_period_minutes = agreement["guaranteed_minutes_per_week"] * weeks

    ts = covering_timesheet(worker["id"], pay_run["period_start"], pay_run["period_end"])
    basis = "TIMESHEET" if ts is not None else "GUARANTEE_FALLBACK"
    entries = ts["entries"] if ts is not None else []

    if agreement["pay_method"] == "GUARANTEED_SALARY_FWW":
        gross_fields = _gross_fww(entries, rate_per_minute,
                                  agreement["guaranteed_minutes_per_week"], weeks,
                                  pack, worker["work_arrangement"], basis)
    else:
        gross_fields = _gross_hourly(entries, rate_per_minute, guaranteed_period_minutes,
                                     pack, worker["work_arrangement"], basis)
    gross_fields["basis"] = basis
    gross_fields["pay_method"] = agreement["pay_method"]
    return gross_fields


def compute_lines_fields(pay_run: dict, worker: dict, agreement: dict, gross: int,
                         same_run_earlier: list[dict], futa_applies: bool) -> dict:
    """Phase 2 of calculate: withholding + employer tax lines over gross_cents.

    same_run_earlier: this run's paychecks already calculated for this worker
    (in calculation order), used by the projected FICA coverage test.
    futa_applies: the run-level projected year applicability of FUTA.
    """
    pack = pack_for_state(worker["work_state_code"])
    year = int(pay_run["pay_date"][:4])

    # --- FICA coverage (projected at calculate time; boundary >= is exact) ---
    cash_before = worker_cash_wages_ytd(worker["id"], year) + sum(
        pc["gross_cents"] for pc in same_run_earlier
    )
    covered_before = cash_before >= FICA_COVERAGE_THRESHOLD_CENTS
    covered_after = (cash_before + gross) >= FICA_COVERAGE_THRESHOLD_CENTS

    if not covered_after:
        fica_base = 0
    elif covered_before:
        fica_base = gross
    else:
        # Crossing check: ALL wages paid this year become FICA wages; the
        # catch-up base is this gross plus the gross of earlier ISSUED checks
        # whose FICA base was 0 (plus same-run earlier checks for the worker).
        fica_base = cash_before + gross

    ss_room = max(0, SS_WAGE_BASE_CENTS - (
        worker_ss_wages_ytd(worker["id"], year)
        + sum(pc.get("_ss_base_cents", 0) for pc in same_run_earlier)
    ))
    ss_base = min(fica_base, ss_room) if fica_base else 0

    fica_wages_before = worker_fica_wages_ytd(worker["id"], year) + sum(
        pc.get("_fica_base_cents", 0) for pc in same_run_earlier
    )
    addl_portion = max(0, fica_wages_before + fica_base - ADDL_MEDICARE_THRESHOLD_CENTS) - max(
        0, fica_wages_before - ADDL_MEDICARE_THRESHOLD_CENTS
    )

    ss_ee = round_half_up_cents(Decimal(ss_base) * SS_RATE) if ss_base else 0
    medicare_ee = round_half_up_cents(Decimal(fica_base) * MEDICARE_RATE) if fica_base else 0
    addl_ee = round_half_up_cents(Decimal(addl_portion) * ADDL_MEDICARE_RATE) if addl_portion else 0
    sit_ee = round_half_up_cents(Decimal(gross) * to_decimal_rate(pack["sit_rate"]))
    fit_ee = agreement["fit_withholding_cents_per_period"]

    withholding_lines = [
        line for line in (
            _line("SS_EE", ss_ee),
            _line("MEDICARE_EE", medicare_ee),
            _line("ADDL_MEDICARE_EE", addl_ee),
            _line("SIT_EE", sit_ee),
            _line("FIT_EE", fit_ee),
        )
        if line is not None
    ]
    net_pay = gross - sum(line["amount_cents"] for line in withholding_lines)

    # --- Employer lines (not deducted from net) ---
    futa_ytd_before = worker_futa_wages_ytd(worker["id"], year) + sum(
        pc.get("_futa_base_cents", 0) for pc in same_run_earlier
    )
    if futa_applies:
        futa_base = min(gross, max(0, FUTA_WAGE_BASE_CENTS - futa_ytd_before))
    else:
        futa_base = 0
    futa_er = round_half_up_cents(Decimal(futa_base) * FUTA_RATE) if futa_base else 0

    suta_ytd_before = worker_suta_wages_ytd(worker["id"], year) + sum(
        pc.get("_suta_base_cents", 0) for pc in same_run_earlier
    )
    suta_base = min(gross, max(0, pack["suta_wage_base_cents"] - suta_ytd_before))
    suta_er = round_half_up_cents(Decimal(suta_base) * to_decimal_rate(pack["suta_rate"])) if suta_base else 0

    ss_er = ss_ee
    medicare_er = medicare_ee
    employer_tax_lines = [
        line for line in (
            _line("SS_ER", ss_er),
            _line("MEDICARE_ER", medicare_er),
            _line("FUTA_ER", futa_er),
            _line("SUTA_ER", suta_er),
        )
        if line is not None
    ]

    return {
        "withholding_lines": withholding_lines,
        "employer_tax_lines": employer_tax_lines,
        "net_pay_cents": net_pay,
        # Internal bases retained for YTD derivations, W-2 lines, and void
        # reversal. Never serialized.
        "_ss_base_cents": ss_base,
        "_fica_base_cents": fica_base,
        "_futa_base_cents": futa_base,
        "_suta_base_cents": suta_base,
    }


def compute_paycheck_fields(pay_run: dict, worker: dict, agreement: dict,
                            same_run_earlier: list[dict],
                            run_total_gross: int | None = None) -> dict:
    """Full derivation for one member paycheck: gross fields plus tax lines.

    run_total_gross: when provided (the sum of this run's member grosses), the
    FUTA year-applicability test projects the run's wages into its quarter.
    """
    gross_fields = compute_gross_fields(pay_run, worker, agreement)
    gross = gross_fields["gross_cents"]
    year = int(pay_run["pay_date"][:4])
    if run_total_gross is None:
        run_total_gross = gross
    futa_applies = employer_quarter_applies_futa(
        pay_run["employer_id"], year, run_total_gross, pay_run["pay_date"]
    )
    lines = compute_lines_fields(pay_run, worker, agreement, gross, same_run_earlier, futa_applies)
    return {**gross_fields, **lines}


def recompute_payrun_totals(pay_run: dict) -> None:
    members = [
        pc for pc in db.paychecks.values()
        if pc["pay_run_id"] == pay_run["id"] and pc["status"] != "VOIDED"
    ]
    pay_run["total_gross_cents"] = sum(pc["gross_cents"] for pc in members)
    pay_run["total_net_cents"] = sum(pc["net_pay_cents"] for pc in members)
    pay_run["total_employer_tax_cents"] = sum(
        line["amount_cents"] for pc in members for line in pc["employer_tax_lines"]
    )
