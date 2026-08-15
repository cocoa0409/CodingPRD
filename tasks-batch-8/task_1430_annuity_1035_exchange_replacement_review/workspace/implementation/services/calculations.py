"""Calculation rules (SCAFFOLD §1.3, PRD §3.4, §3.7, §3.8).

All monetary math is integer cents; all rates are integer basis points.
Division by 10000 is performed exactly once, with floor semantics.
"""
from datetime import date, timedelta

import db

# Constants (SCAFFOLD §1.3)
SETTLEMENT_LAG_DAYS = 45
MIN_PARTIAL_CENTS = 100000
RIDER_LOSS_CAP_CENTS = 2000000
MAX_PROJECTION_YEARS = 30
FREE_LOOK_DAYS_STANDARD = 20
FREE_LOOK_DAYS_SENIOR = 30
SENIOR_AGE = 65
CHURN_FLAG_MIN_COMPLETED_12M = 2
RESCISSION_FLAG_BPS = 5000
ANTI_CHURN_WINDOW_DAYS = 365
COOLING_OFF_DAYS_AFTER_RESCISSION = 30


def floor_div(a: int, b: int) -> int:
    """Integer floor division."""
    return a // b


def completed_years(issue_date_iso: str, as_of_dt) -> int:
    """Number of completed whole years since issue_date as of as_of_dt.

    Anniversary arithmetic is inclusive: on the exact anniversary date, the
    year counts as completed.
    """
    issue_d = date.fromisoformat(issue_date_iso)
    as_of_date = as_of_dt.date() if hasattr(as_of_dt, "date") else as_of_dt
    # Largest k >= 0 such that issue_date + k years <= as_of_date
    k = 0
    while True:
        try:
            next_anniv = date(issue_d.year + k + 1, issue_d.month, issue_d.day)
        except ValueError:
            # Feb 29 edge: anniversary on a non-leap year is Feb 28
            next_anniv = date(issue_d.year + k + 1, issue_d.month, 28)
        if next_anniv <= as_of_date:
            k += 1
        else:
            break
    return k


def surrender_pct_bps(schedule, issue_date_iso: str, as_of_dt) -> int:
    """Look up the schedule pct at the given as-of instant.

    year_index = completed_years + 1; entry with contract_year == year_index
    supplies the pct; 0 when year_index exceeds the schedule length.
    """
    cy = completed_years(issue_date_iso, as_of_dt)
    year_index = cy + 1
    for entry in schedule:
        if entry["contract_year"] == year_index:
            return int(entry["pct_bps"])
    return 0


def surrender_charge_cents(exchange_base_cents: int, pct_bps: int) -> int:
    """floor(exchange_base_cents * pct_bps / 10000); divide exactly once."""
    return (exchange_base_cents * pct_bps) // 10000


def compute_analysis_fields(case: dict, contract: dict, analysis_dt,
                            assumed_old_growth_bps: int, assumed_new_growth_bps: int) -> dict:
    """Compute every computed field on a ComparisonAnalysis.

    Pinned evaluation order per SCAFFOLD §1.3 net_replacement_cost:
      1. surrender_charge = schedule[at_settlement] on exchange_base
      2. amount_received = exchange_base - surrender_charge
      3. bonus_credit = floor(amount_received * bonus_bps / 10000)
      4. benefit_loss = benefit_loss_estimate
      5. net_replacement_cost = surrender_charge + benefit_loss - bonus_credit
    """
    # Exchange base
    if case["exchange_type"] == "FULL":
        exchange_base = contract["account_value_cents"]
    else:
        exchange_base = case["exchange_amount_cents"]

    # Chronological variant (as-of today = analysis_date)
    pct_today = surrender_pct_bps(
        contract["surrender_schedule"], contract["issue_date"], analysis_dt
    )
    charge_today = surrender_charge_cents(exchange_base, pct_today)

    # Forward-looking variant (as-of analysis_date + 45 days)
    settlement_dt = analysis_dt + timedelta(days=SETTLEMENT_LAG_DAYS)
    pct_settlement = surrender_pct_bps(
        contract["surrender_schedule"], contract["issue_date"], settlement_dt
    )
    charge_settlement = surrender_charge_cents(exchange_base, pct_settlement)

    amount_received = exchange_base - charge_settlement
    bonus_credit = (amount_received * case["new_product_bonus_bps"]) // 10000

    # Benefit loss
    if not contract["living_benefit_rider"]:
        benefit_loss = 0
    else:
        in_the_money = contract["rider_benefit_base_cents"] - contract["account_value_cents"]
        benefit_loss = max(0, min(in_the_money, RIDER_LOSS_CAP_CENTS))

    net_replacement_cost = charge_settlement + benefit_loss - bonus_credit

    # Tax basis allocation (multiply-then-divide; never round the ratio first)
    if case["exchange_type"] == "FULL":
        basis_transferred = contract["tax_basis_cents"]
        basis_remaining = 0
    else:
        basis_transferred = (
            contract["tax_basis_cents"] * case["exchange_amount_cents"]
        ) // contract["account_value_cents"]
        basis_remaining = contract["tax_basis_cents"] - basis_transferred

    # Break-even projection (year-by-year compounding, floor each step)
    if contract["living_benefit_rider"]:
        net_old_bps = assumed_old_growth_bps - contract["rider_annual_fee_bps"]
    else:
        net_old_bps = assumed_old_growth_bps
    net_new_bps = assumed_new_growth_bps - case["new_product_annual_fee_bps"]

    old_bal = contract["account_value_cents"]
    new_bal = amount_received + bonus_credit
    break_even = 99
    for y in range(1, MAX_PROJECTION_YEARS + 1):
        old_bal = (old_bal * (10000 + net_old_bps)) // 10000
        new_bal = (new_bal * (10000 + net_new_bps)) // 10000
        if new_bal >= old_bal:
            break_even = y
            break

    return {
        "exchange_base_cents": exchange_base,
        "surrender_pct_bps_today": pct_today,
        "surrender_charge_today_cents": charge_today,
        "surrender_pct_bps_at_settlement": pct_settlement,
        "surrender_charge_at_settlement_cents": charge_settlement,
        "amount_received_cents": amount_received,
        "bonus_credit_cents": bonus_credit,
        "benefit_loss_cents": benefit_loss,
        "net_replacement_cost_cents": net_replacement_cost,
        "break_even_years": break_even,
        "basis_transferred_cents": basis_transferred,
        "basis_remaining_cents": basis_remaining,
    }


def compute_age_years(dob_iso: str, as_of_dt) -> int:
    """Whole years between date_of_birth and the logical clock date."""
    dob = date.fromisoformat(dob_iso)
    d = as_of_dt.date() if hasattr(as_of_dt, "date") else as_of_dt
    years = d.year - dob.year
    if (d.month, d.day) < (dob.month, dob.day):
        years -= 1
    return years


def free_look_deadline_date(free_look_started_dt, is_senior: bool) -> str:
    """free_look_deadline_date = date(free_look_started_at) + free_look_days.

    The delivery date itself is day 0; the deadline is the date after
    free_look_days additional days.
    """
    days = FREE_LOOK_DAYS_SENIOR if is_senior else FREE_LOOK_DAYS_STANDARD
    start_date = free_look_started_dt.date()
    deadline = start_date + timedelta(days=days)
    return deadline.isoformat()
