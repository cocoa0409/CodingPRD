"""Monetary calculations with exact decimal arithmetic (PRD §2.6, §3.2, §3.5, §3.8).

All money is integer whole cents. Where a computation produces a fractional
cent, the result is rounded half up. Rounding points are pinned per the PRD.
"""
from decimal import Decimal, ROUND_HALF_UP


def round_half_up(value):
    """Round a Decimal (or numeric) to the nearest whole integer, half up."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---- premium_calculation constants (SCAFFOLD §1.3, PRD §3.2) ----
BASE_POLICY_FEE_CENTS = 12000
PP_RATE = Decimal("0.004")
LIAB_RATE = Decimal("0.0008")
LOU_RATE = Decimal("0.0015")
SCHED_RATE = Decimal("0.018")
BUNDLE_DISCOUNT_FACTOR = Decimal("0.90")
INSTALLMENT_SURCHARGE_PCT = Decimal("0.05")
TERRITORY_FACTORS = {
    "HIGH": Decimal("1.25"),
    "STANDARD": Decimal("1.00"),
    "LOW": Decimal("0.85"),
}

# ---- claim_settlement constant ----
MAX_DEPRECIATION_PCT = Decimal("0.80")

# ---- cancellation_refund constant ----
SHORT_RATE_PENALTY_PCT = Decimal("0.10")


def compute_premium(pp_limit, liab_limit, lou_limit, sched_sum, territory_code, discount_active):
    """annual_premium_cents per PRD §3.2.

    Each of the four rate components is rounded half up before being added into
    the subtotal; the final product is rounded half up once.
    """
    subtotal = (
        BASE_POLICY_FEE_CENTS
        + round_half_up(Decimal(pp_limit) * PP_RATE)
        + round_half_up(Decimal(liab_limit) * LIAB_RATE)
        + round_half_up(Decimal(lou_limit) * LOU_RATE)
        + round_half_up(Decimal(sched_sum) * SCHED_RATE)
    )
    territory_factor = TERRITORY_FACTORS[territory_code]
    bundle_factor = BUNDLE_DISCOUNT_FACTOR if discount_active else Decimal("1.00")
    return round_half_up(Decimal(subtotal) * territory_factor * bundle_factor)


def monthly_installment(annual_premium_cents):
    """One MONTHLY installment = round_half_up(annual * 1.05 / 12) (PRD §3.3)."""
    return round_half_up(Decimal(annual_premium_cents) * Decimal("1.05") / Decimal("12"))


def covered_item_cents(valuation_method, loss_type, replacement_cost_cents,
                       age_months, useful_life_months):
    """Per-item covered amount under the claim's frozen valuation method (PRD §3.8)."""
    if valuation_method == "ACV" and loss_type == "PERSONAL_PROPERTY":
        depreciation_pct = Decimal(age_months) / Decimal(useful_life_months)
        if depreciation_pct > MAX_DEPRECIATION_PCT:
            depreciation_pct = MAX_DEPRECIATION_PCT
        return round_half_up(Decimal(replacement_cost_cents) * (Decimal("1") - depreciation_pct))
    # RCV, or any LIABILITY / LOSS_OF_USE loss -> full replacement cost.
    return int(replacement_cost_cents)


def cancellation_refund(refund_method, effective_date, expiry_date, cancel_clock, paid_premium):
    """Pro-rata / short-rate refund (PRD §3.5).

    term_days   = whole days (expiry - effective)
    elapsed_days = whole days (cancel_clock - effective), clamped to [0, term_days]
    unused_days  = term_days - elapsed_days
    pro_rata = round_half_up(paid_premium * unused_days / term_days)
    """
    term_days = (expiry_date - effective_date).days
    if term_days <= 0:
        return 0
    elapsed_days = (cancel_clock - effective_date).days
    if elapsed_days < 0:
        elapsed_days = 0
    if elapsed_days > term_days:
        elapsed_days = term_days
    unused_days = term_days - elapsed_days
    pro_rata = round_half_up(Decimal(paid_premium) * Decimal(unused_days) / Decimal(term_days))
    if refund_method == "PRO_RATA":
        return pro_rata
    # SHORT_RATE
    penalty = round_half_up(Decimal(paid_premium) * SHORT_RATE_PENALTY_PCT)
    return max(0, pro_rata - penalty)
