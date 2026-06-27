"""Calculation rules (SCAFFOLD §1.3 / PRD §3).

All monetary values are integer cents. Percentages are fractions preserving input
precision; only resulting cent amounts are rounded.
"""

from decimal import Decimal, ROUND_HALF_UP

from validate import round_half_up, floor_cents, ceil_cents

# Constants
EARLY_BUYOUT_FEE_CENTS = 5000
LATE_FEE_CENTS = 1500
DEFAULT_THRESHOLD = 3
MIN_BENCH_CENTS = 4000
RUSH_PCT = Decimal("0.25")
MIN_FINANCE_SCORE = 660

TRADEIN_PCT = {
    "NEW": Decimal("0.60"),
    "USED": Decimal("0.50"),
    "VINTAGE": Decimal("0.70"),
}

VOLUME_THRESHOLD = 8
VOLUME_PCT = Decimal("0.15")
BUNDLE_PCT = Decimal("0.20")

APR_TIER_PRIME = 0.0599
APR_TIER_NEAR_PRIME = 0.1299
APR_TIER_SUBPRIME = 0.2299
SCORE_PRIME_MIN = 720
SCORE_NEAR_PRIME_MIN = 660


def equity_accrual(months_paid, monthly_rate_cents, equity_rate_pct, purchase_price_cents,
                   equity_cap_pct, plan):
    """§1.3 equity_accrual. RENTAL plan -> equity_rate treated as 0 -> 0."""
    rate = Decimal("0") if plan == "RENTAL" else Decimal(str(equity_rate_pct))
    raw = Decimal(months_paid) * Decimal(monthly_rate_cents) * rate
    raw_equity = int(raw.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    cap = floor_cents(Decimal(purchase_price_cents) * Decimal(str(equity_cap_pct)))
    return min(raw_equity, cap)


def buyout_payoff(purchase_price_cents, accrued_equity_cents, late_fee_balance_cents):
    """§1.3 buyout_payoff. Counts down from purchase price; adds fee + late fees."""
    remaining = purchase_price_cents - accrued_equity_cents
    payoff = remaining + EARLY_BUYOUT_FEE_CENTS + late_fee_balance_cents
    return max(0, payoff)


def tradein_offer(appraised_value_cents, condition):
    """§1.3 tradein_offer. Condition-tiered fraction of appraised value, floored."""
    pct = TRADEIN_PCT[condition]
    return floor_cents(Decimal(appraised_value_cents) * pct)


def consignment_settlement(ask_price_cents, commission_pct):
    """§1.3 consignment_settlement. Commission round_half_up, payout = ask - commission."""
    commission = round_half_up(Decimal(ask_price_cents) * Decimal(str(commission_pct)))
    return ask_price_cents - commission


def repair_invoice(labor_hours, labor_rate_cents, parts_cost_cents, rush):
    """§1.3 repair_invoice. labor floored at MIN_BENCH; rush surcharge on subtotal."""
    labor = round_half_up(Decimal(str(labor_hours)) * Decimal(labor_rate_cents))
    labor = max(labor, MIN_BENCH_CENTS)
    subtotal = labor + parts_cost_cents
    surcharge = (RUSH_PCT * Decimal(subtotal)) if rush else Decimal(0)
    total = Decimal(subtotal) + surcharge
    return round_half_up(total)


def apr_for_score(credit_score):
    if credit_score >= SCORE_PRIME_MIN:
        return APR_TIER_PRIME
    if credit_score >= SCORE_NEAR_PRIME_MIN:
        return APR_TIER_NEAR_PRIME
    return APR_TIER_SUBPRIME


def financing_terms(principal_cents, term_months, credit_score):
    """§1.3 financing_terms. Round ONCE at the very end (round_half_up)."""
    apr = apr_for_score(credit_score)
    r = apr / 12.0  # exact, unrounded
    n = term_months
    if r == 0:
        exact = principal_cents / n
    else:
        factor = (1 + r) ** n
        exact = principal_cents * r * factor / (factor - 1)
    monthly = round_half_up(exact)
    return apr, monthly


def lesson_tuition(base_rate_cents, sessions_per_month, has_active_bundle):
    """§1.3 lesson_tuition. Volume discount first, then bundle; round after each step."""
    base_monthly = base_rate_cents * sessions_per_month
    vol_pct = VOLUME_PCT if sessions_per_month >= VOLUME_THRESHOLD else Decimal(0)
    after_volume = round_half_up(Decimal(base_monthly) * (Decimal(1) - vol_pct))
    bundle_pct = BUNDLE_PCT if has_active_bundle else Decimal(0)
    return round_half_up(Decimal(after_volume) * (Decimal(1) - bundle_pct))


def layaway_paid(deposit_cents, installments):
    paid = deposit_cents + sum(installments)
    return paid


def layaway_remaining(total_price_cents, paid_cents):
    return max(0, total_price_cents - paid_cents)


def layaway_cancel_refund(total_price_cents, restock_fee_pct, paid_cents):
    restock = round_half_up(Decimal(total_price_cents) * Decimal(str(restock_fee_pct)))
    return max(0, paid_cents - restock)


def special_order_deposit(quoted_price_cents, deposit_pct):
    return ceil_cents(Decimal(quoted_price_cents) * Decimal(str(deposit_pct)))
