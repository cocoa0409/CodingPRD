"""Calculation rules (PRD §3.6, §3.3, §3.9, §3.11, §3.12, §2.5 / scaffold §1.3).

All money is integer cents; non-integer intermediates rounded half-up to whole cents.
utilization_pct and eligibility_score are 4-decimal numbers, round-half-up.
"""
import calendar
from decimal import Decimal, ROUND_HALF_UP

from clock import parse_iso

# --- Pinned constants (scaffold §1.3) ---
OVERAGE_TIER1_LIMIT = 200          # mileage_overage
EARLY_PENALTY_PCT = Decimal("0.50")  # early_cancel_fee
W_CREDIT = Decimal("0.5")          # eligibility_score
W_INCOME = Decimal("0.3")
W_HISTORY = Decimal("0.2")
INCOME_RATIO_CAP = Decimal("5")
SWAP_FEE_CENTS = 7500              # swap_net_adjustment
FLAT_ETF_CENTS = 160000           # chronological cancel-quote flat early-termination fee


def _round_cents(value):
    """Round a Decimal to the nearest whole cent, round-half-up. Returns int."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _round4(value):
    """Round a Decimal to 4 decimal places, round-half-up. Returns float."""
    q = Decimal(value).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
    return float(q)


# ---------------------------------------------------------------------------
# mileage_overage (PRD §3.6)
# ---------------------------------------------------------------------------
def mileage_overage(plan, odometer_start_miles, odometer_end_miles):
    delta = odometer_end_miles - odometer_start_miles  # >= 0 enforced by validation
    billable = max(0, delta - plan["included_miles_per_cycle"] - plan["free_buffer_miles"])
    tier1 = min(billable, OVERAGE_TIER1_LIMIT)
    tier2 = max(0, billable - OVERAGE_TIER1_LIMIT)
    raw = (Decimal(tier1) * Decimal(plan["overage_tier1_rate_cents"])
           + Decimal(tier2) * Decimal(plan["overage_tier2_rate_cents"]))
    return _round_cents(raw)


# ---------------------------------------------------------------------------
# eligibility_score (PRD §3.3)
# ---------------------------------------------------------------------------
def eligibility_decision(applicant, plan):
    """Returns (status, score_float, required_deposit_cents_or_None)."""
    norm_credit = (Decimal(applicant["credit_score"]) - Decimal(300)) / Decimal(550)
    income_ratio = min(
        Decimal(applicant["monthly_income_cents"]) / Decimal(plan["monthly_fee_cents"]),
        INCOME_RATIO_CAP,
    )
    norm_income = income_ratio / INCOME_RATIO_CAP
    hist = {"CLEAN": Decimal("1.0"), "MINOR": Decimal("0.5"), "SEVERE": Decimal("0.0")}[
        applicant["history_flag"]
    ]
    raw = W_CREDIT * norm_credit + W_INCOME * norm_income + W_HISTORY * hist
    score = Decimal(raw).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)

    # Tier boundaries inclusive at the lower edge (PRD §3.3).
    if score >= Decimal("0.80"):
        status = "APPROVED"
        deposit = plan["deposit_base_cents"] * 1
    elif score >= Decimal("0.60"):
        status = "CONDITIONAL"
        deposit = plan["deposit_base_cents"] * 2
    else:
        status = "DECLINED"
        deposit = None
    return status, float(score), deposit


# ---------------------------------------------------------------------------
# swap_net_adjustment (PRD §3.9)
# ---------------------------------------------------------------------------
def swap_proration_window(cycle_start_iso, now_dt):
    """Returns (cycle_days, remaining_days). cycle_days = days in the calendar month
    of cycle_start_iso; remaining_days = whole days from now to cycle_start + cycle_days."""
    start = parse_iso(cycle_start_iso)
    cycle_days = calendar.monthrange(start.year, start.month)[1]
    window_end = start + _timedelta_days(cycle_days)
    delta_seconds = (window_end - now_dt).total_seconds()
    remaining_days = int(delta_seconds // 86400)  # floor whole days
    if remaining_days < 0:
        remaining_days = 0
    return cycle_days, remaining_days


def _timedelta_days(n):
    from datetime import timedelta
    return timedelta(days=n)


def swap_net_adjustment(from_plan, to_plan, cycle_start_iso, now_dt, swaps_used):
    cycle_days, remaining_days = swap_proration_window(cycle_start_iso, now_dt)
    # step 1: credit old; step 2: charge new — each rounded independently before sum.
    credit_old = _round_cents(
        Decimal(from_plan["monthly_fee_cents"]) * Decimal(remaining_days) / Decimal(cycle_days)
    )
    charge_new = _round_cents(
        Decimal(to_plan["monthly_fee_cents"]) * Decimal(remaining_days) / Decimal(cycle_days)
    )
    # step 3: swap fee gated on swaps_used BEFORE increment, against originating plan.
    if swaps_used >= from_plan["included_swaps_per_term"]:
        swap_fee = SWAP_FEE_CENTS
    else:
        swap_fee = 0
    # step 4: net (may be negative on a downgrade).
    net = charge_new - credit_old + swap_fee
    return swap_fee, net


# ---------------------------------------------------------------------------
# early_cancel_fee — forward-looking (PRD §3.12)
# ---------------------------------------------------------------------------
def elapsed_full_months(term_start_iso, now_dt):
    """Whole months between term_start and now, floored."""
    start = parse_iso(term_start_iso)
    months = (now_dt.year - start.year) * 12 + (now_dt.month - start.month)
    # If the day-of-month/time of `now` is before the anchor within the month,
    # the final month has not fully elapsed.
    if (now_dt.day, now_dt.hour, now_dt.minute, now_dt.second, now_dt.microsecond) < (
        start.day, start.hour, start.minute, start.second, start.microsecond
    ):
        months -= 1
    return max(0, months)


def early_cancel_fee_forward(plan, term_start_iso, now_dt):
    elapsed = elapsed_full_months(term_start_iso, now_dt)
    remaining = max(0, plan["min_term_months"] - elapsed)
    raw = Decimal(remaining) * Decimal(plan["monthly_fee_cents"]) * EARLY_PENALTY_PCT
    return _round_cents(raw)


# ---------------------------------------------------------------------------
# early_cancel_fee — chronological (PRD §3.12 cancel-quote mode=CHRONOLOGICAL)
# ---------------------------------------------------------------------------
def early_cancel_fee_chronological(plan, cycle_start_iso, now_dt):
    """FLAT_ETF + round(monthly_fee / current_cycle_day_count * unbilled_days_in_open_cycle)."""
    start = parse_iso(cycle_start_iso)
    cycle_days = calendar.monthrange(start.year, start.month)[1]
    window_end = start + _timedelta_days(cycle_days)
    unbilled_days = int((window_end - now_dt).total_seconds() // 86400)
    if unbilled_days < 0:
        unbilled_days = 0
    raw = Decimal(plan["monthly_fee_cents"]) * Decimal(unbilled_days) / Decimal(cycle_days)
    return FLAT_ETF_CENTS + _round_cents(raw)


# ---------------------------------------------------------------------------
# deposit_settlement_waterfall (PRD §3.11)
# ---------------------------------------------------------------------------
def deposit_waterfall(total_damage_cents, unpaid_cycle_sum, unpaid_early_cancel_sum, deposit_held_cents):
    outstanding = total_damage_cents + unpaid_cycle_sum + unpaid_early_cancel_sum
    deposit_applied = min(deposit_held_cents, outstanding)
    deposit_refunded = deposit_held_cents - deposit_applied
    balance_due = outstanding - deposit_applied
    return deposit_applied, deposit_refunded, balance_due


# ---------------------------------------------------------------------------
# fleet_utilization (PRD §2.5, §3.7)
# ---------------------------------------------------------------------------
def utilization_pct(in_use_count, total_vehicles):
    if total_vehicles <= 0:
        return 0  # empty fleet reads exactly 0 (PRD §2.5)
    return _round4(Decimal(in_use_count) / Decimal(total_vehicles))
