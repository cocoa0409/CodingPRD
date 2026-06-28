"""Calculation primitives. Money is integer cents; rounding is round-half-up
(half rounds away from zero) per PRD §2.7."""
from decimal import Decimal, ROUND_HALF_UP


def round_half_up(value):
    """Round a numeric (Decimal/int/float-as-Decimal) to the nearest integer,
    half away from zero. Returns int."""
    d = value if isinstance(value, Decimal) else Decimal(str(value))
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def earnings_split(amount_cents, balance_cents, earnings_cents):
    """distribution_earnings_split: pro-rata earnings ratio captured at disbursement.

    Returns (earnings_portion_cents, basis_portion_cents).
    """
    if balance_cents == 0:
        ratio = Decimal(0)
    else:
        ratio = Decimal(earnings_cents) / Decimal(balance_cents)
    earnings_portion = round_half_up(Decimal(amount_cents) * ratio)
    basis_portion = amount_cents - earnings_portion
    return earnings_portion, basis_portion


def nonqualified_additional_tax(amount_cents, earnings_portion_cents, qualified_sum_cents, tax_pct):
    """nonqualified_penalty: 10% (program rate) on the earnings portion of the
    non-qualified amount. Returns (qualified, nonqualified, additional_tax)."""
    qualified = qualified_sum_cents
    nonqualified = max(0, amount_cents - qualified)
    if amount_cents == 0:
        nonqual_earnings = Decimal(0)
    else:
        nonqual_earnings = Decimal(earnings_portion_cents) * (
            Decimal(nonqualified) / Decimal(amount_cents)
        )
    additional_tax = round_half_up(nonqual_earnings * Decimal(str(tax_pct)))
    return qualified, nonqualified, additional_tax


def management_fee(period_end_balance_cents, months, fee_bps):
    """program_management_fee: round per-month then sum. Returns total fee cents."""
    monthly_rate = (Decimal(fee_bps) / Decimal(10000)) / Decimal(12)
    monthly_fee = round_half_up(Decimal(period_end_balance_cents) * monthly_rate)
    return monthly_fee * months


def medicaid_payback(balance_cents, pending_approved_cents, claimed_amount_cents,
                     premiums_paid_cents):
    """medicaid_payback waterfall. Returns (allowed_payback, residual_to_estate)."""
    after_bucket1 = max(0, balance_cents - pending_approved_cents)
    claimable = max(0, claimed_amount_cents - premiums_paid_cents)
    allowed_payback = min(after_bucket1, claimable)
    residual = after_bucket1 - allowed_payback
    return allowed_payback, residual
