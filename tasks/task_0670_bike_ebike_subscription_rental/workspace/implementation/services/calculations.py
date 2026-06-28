"""Calculation rules (SCAFFOLD §1.3 / PRD §2.6, §3.8, §3.9, §3.11).

All money is integer cents. Fractional multiplications are rounded HALF UP.
Round-then-sum where a per-unit charge is multiplied by a rate then accumulated.
"""
import math
from decimal import Decimal, ROUND_HALF_UP

# ---- class surcharge constants (§3.8) ----
SURCHARGE = {
    "STANDARD": 0,
    "EBIKE": 2000,
    "CARGO_EBIKE": 4000,
}

# ---- cost_of_rental constants ----
TIER1_DAYS = 6           # days 1..6 full rate
TIER2_LAST_DAY = 29      # days 7..29 at 0.85
TIER2_RATE = Decimal("0.85")
TIER3_RATE = Decimal("0.70")
CYCLE_DAYS = 30

# ---- buyout constants ----
EQUITY_PCT_PER_CYCLE = Decimal("0.03")
EQUITY_CAP_PCT = Decimal("0.60")

# ---- late fee ----
LATE_FEE_PER_DAY_CENTS = 1500

# ---- fleet invoice ----
VOLUME_THRESHOLD = 5
VOLUME_DISCOUNT_PCT = Decimal("0.10")

# ---- coverage cap ----
THEFT_CAP_PCT = Decimal("1.00")
DAMAGE_CAP_PCT = Decimal("0.40")

SECONDS_PER_DAY = 86400


def round_half_up(value):
    """Round a Decimal (or int) half-up to the nearest whole integer cent."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def surcharge_for(model_class):
    return SURCHARGE[model_class]


def _whole_days_floor(later, earlier):
    """floor((later - earlier) / 1 day) — zero-based whole days."""
    delta = (later - earlier).total_seconds()
    return int(math.floor(delta / SECONDS_PER_DAY))


def _whole_days_ceil(later, earlier):
    """ceil((later - earlier) / 1 day)."""
    delta = (later - earlier).total_seconds()
    return int(math.ceil(delta / SECONDS_PER_DAY))


# =============================================================================
# cost_of_rental (§3.8)
# =============================================================================

def monthly_first_cycle_charge(model, reserved_at, activated_at):
    """MONTHLY variant: prorated first cycle.

    effective_monthly = monthly_fee + class surcharge
    day_offset = floor((activated_at - reserved_at) / 1 day)   # zero-based whole days
    remaining_days = 30 - day_offset
    first_cycle_charge = round_half_up(effective_monthly * remaining_days / 30)
    """
    effective_monthly = model["monthly_fee_cents"] + surcharge_for(model["model_class"])
    day_offset = _whole_days_floor(activated_at, reserved_at)
    remaining_days = CYCLE_DAYS - day_offset
    charge = Decimal(effective_monthly) * Decimal(remaining_days) / Decimal(CYCLE_DAYS)
    return round_half_up(charge)


def daily_tiered_charge(model, activated_at, returned_at):
    """DAILY variant: tiered marginal day rate, round-then-sum.

    effective_daily = daily_rate + class surcharge
    billed_days = max(1, ceil((returned_at - activated_at) / 1 day))
    day 1..6 -> full; day 7..29 -> *0.85 (round half up); day 30+ -> *0.70 (round half up)
    """
    effective_daily = model["daily_rate_cents"] + surcharge_for(model["model_class"])
    billed_days = max(1, _whole_days_ceil(returned_at, activated_at))
    total = 0
    for d in range(1, billed_days + 1):
        if d <= TIER1_DAYS:
            total += effective_daily
        elif d <= TIER2_LAST_DAY:
            total += round_half_up(Decimal(effective_daily) * TIER2_RATE)
        else:
            total += round_half_up(Decimal(effective_daily) * TIER3_RATE)
    return total


# =============================================================================
# buyout_price (§3.8)
# =============================================================================

def buyout_price(model, rental):
    """Return (quoted_price_cents, equity_credit_cents)."""
    base = model["purchase_price_cents"]
    if rental["rental_mode"] == "MONTHLY":
        raw_equity = round_half_up(
            Decimal(base) * EQUITY_PCT_PER_CYCLE * Decimal(rental["completed_cycles"])
        )
        equity_cap = round_half_up(Decimal(base) * EQUITY_CAP_PCT)
        equity_credit = min(raw_equity, equity_cap)
        quoted = base - equity_credit
        return quoted, equity_credit
    # DAILY: no equity
    return base, 0


# =============================================================================
# late_fee (§3.9)
# =============================================================================

def late_fee(return_due_clock, returned_at_clock):
    if returned_at_clock <= return_due_clock:
        return 0
    days_late = _whole_days_ceil(returned_at_clock, return_due_clock)
    return days_late * LATE_FEE_PER_DAY_CENTS


# =============================================================================
# return_settlement (§3.9)
# =============================================================================

def return_settlement(deposit_cents, damage_charge_cents, cleaning_fee_cents, late_fee_cents):
    """Return dict with total_assessed/deposit_applied/overflow_billed/deposit_refund."""
    total_assessed = damage_charge_cents + cleaning_fee_cents + late_fee_cents
    deposit_applied = min(deposit_cents, total_assessed)
    overflow_billed = max(0, total_assessed - deposit_cents)
    deposit_refund = max(0, deposit_cents - total_assessed)
    return {
        "total_assessed_cents": total_assessed,
        "deposit_applied_cents": deposit_applied,
        "overflow_billed_cents": overflow_billed,
        "deposit_refund_cents": deposit_refund,
    }


# =============================================================================
# fleet_invoice (§3.11)
# =============================================================================

def fleet_invoice_amounts(lines_with_models):
    """lines_with_models: list of (rental, model) ordered by created_at ASC.
    Returns dict line_count/gross_amount_cents/discount_cents/amount_due_cents."""
    per_line = []
    for _rental, model in lines_with_models:
        per_line.append(model["monthly_fee_cents"] + surcharge_for(model["model_class"]))
    line_count = len(per_line)
    gross = sum(per_line)
    if line_count >= VOLUME_THRESHOLD:
        amount_due = 0
        for charge in per_line:
            amount_due += round_half_up(Decimal(charge) * (Decimal(1) - VOLUME_DISCOUNT_PCT))
    else:
        amount_due = gross
    discount = gross - amount_due
    return {
        "line_count": line_count,
        "gross_amount_cents": gross,
        "discount_cents": discount,
        "amount_due_cents": amount_due,
    }


# =============================================================================
# coverage_cap (§3.10)
# =============================================================================

def coverage_max_payout(model, claim):
    base = model["purchase_price_cents"]
    pct = THEFT_CAP_PCT if claim["claim_type"] == "THEFT" else DAMAGE_CAP_PCT
    cap = round_half_up(Decimal(base) * pct)
    return min(claim["claimed_amount_cents"], cap)
