"""Calculation rules (PRD §2.5 + §3.x, SCAFFOLD §1.3).

All valuation figures are WHOLE DOLLARS rounded half-up to integer dollars.
All ledger figures are INTEGER CENTS; where derived from a product the
full-precision product is computed first and rounded half-up to a whole cent
exactly once at the end. Decimal is used throughout — never float.
"""
from decimal import Decimal, ROUND_HALF_UP


def D(x):
    """Coerce any numeric/str to Decimal safely (avoids float artifacts)."""
    if isinstance(x, Decimal):
        return x
    if isinstance(x, bool):
        return Decimal(int(x))
    return Decimal(str(x))


def round_half_up_int(value):
    """Round a numeric to the nearest integer, half-up."""
    return int(D(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# Exemption deduction constants (SCAFFOLD §1.3 calc exemption_deduction)
HOMESTEAD_FLAT = 7000
SENIOR_FLAT = 5000
SENIOR_PCT = Decimal("0.10")
VETERAN_FLAT = 4000
DISABILITY_FACTOR = Decimal("0.50")


def capped_base_value(market_value, prior_base, growth_cap_pct, reassessment_event):
    """SCAFFOLD calc capped_base_value / PRD §3.3.

    NONE and prior_base > 0  -> min(market_value, prior_base*(1+cap))
    SALE/NEW_CONSTRUCTION, or prior_base == 0 -> market_value (rebase).
    Whole dollars, round half-up. assessed_value == capped_base_value.
    """
    mv = D(market_value)
    pb = D(prior_base)
    cap = D(growth_cap_pct)
    if reassessment_event == "NONE" and pb > 0:
        ceiling = pb * (Decimal(1) + cap)
        base = min(mv, ceiling)
    else:
        base = mv
    return round_half_up_int(base)


def exemption_deduction(exemption_type, assessed_value, owner):
    """SCAFFOLD calc exemption_deduction / PRD §3.4.

    Returns claimed_amount (whole dollars), clamped to <= assessed_value.
    Each deduction is computed against the SAME pre-exemption assessed_value.
    """
    av = D(assessed_value)
    if exemption_type == "HOMESTEAD":
        raw = D(HOMESTEAD_FLAT)
    elif exemption_type == "SENIOR":
        pct_amt = round_half_up_int(av * SENIOR_PCT)
        raw = D(max(SENIOR_FLAT, pct_amt))
    elif exemption_type == "VETERAN":
        raw = D(VETERAN_FLAT)
    elif exemption_type == "DISABILITY":
        dpct = D(owner.get("disability_pct", 0))
        raw = D(round_half_up_int(av * (dpct / D(100)) * DISABILITY_FACTOR))
    else:
        raw = Decimal(0)
    raw_int = round_half_up_int(raw)
    return min(raw_int, round_half_up_int(av))


def exemption_total_and_taxable(assessed_value, approved_claimed_amounts):
    """SCAFFOLD calc exemption_total / PRD §3.5.

    Sum approved claimed_amounts (each already computed against the same AV),
    clamp the SUM to <= assessed_value, then taxable = max(0, AV - total).
    """
    av = round_half_up_int(assessed_value)
    raw_sum = sum(int(a) for a in approved_claimed_amounts)
    exemption_total = min(raw_sum, av)
    taxable_value = max(0, av - exemption_total)
    return exemption_total, taxable_value


def tax_bill_amount_cents(billed_taxable_value, mill_rate):
    """SCAFFOLD calc tax_bill_amount / PRD §3.8.

    cents = round_half_up(btv * mill_rate / 10), single rounding after the
    full-precision product (btv*mr/1000 dollars -> *100 cents == btv*mr/10).
    """
    btv = D(billed_taxable_value)
    mr = D(mill_rate)
    return round_half_up_int(btv * mr / D(10))


def period_interest_cents(deferred_principal_cents, principal_paid_cents,
                          annual_interest_rate):
    """SCAFFOLD calc deferral_interest_accrual / PRD §3.9 (declining balance).

    interest = round_half_up((deferred_principal - principal_already_repaid)
                              * annual_interest_rate)
    """
    outstanding_principal = D(deferred_principal_cents) - D(principal_paid_cents)
    return round_half_up_int(outstanding_principal * D(annual_interest_rate))


def payment_waterfall(amount_cents, accrued_interest_cents, interest_paid_cents,
                      deferred_principal_cents, principal_paid_cents):
    """SCAFFOLD calc deferral_payment_waterfall / PRD §3.9 (interest-first).

    Returns (applied_to_interest_cents, applied_to_principal_cents).
    Interest bucket is exhausted before any cent touches principal.
    All values are integer cents; no rounding needed.
    """
    interest_due = accrued_interest_cents - interest_paid_cents
    applied_to_interest = min(amount_cents, interest_due)
    remainder = amount_cents - applied_to_interest
    principal_due = deferred_principal_cents - principal_paid_cents
    applied_to_principal = min(remainder, principal_due)
    return applied_to_interest, applied_to_principal
