"""Monetary calculations (calculation agency_fee_total, scaffold §1.3).

Money is integer cents. The sliding-scale multiplication is rounded HALF-UP per
component (round-then-sum), never on the sum.
"""
from decimal import Decimal, ROUND_HALF_UP

from models import (
    LOW_BAND_CENTS,
    HIGH_BAND_CENTS,
    REIMBURSABLE_CAP_CENTS,
)


def sliding_scale_pct(income_cents):
    """Step 1: income-band threshold selection (non-linear branch)."""
    if income_cents < LOW_BAND_CENTS:
        return Decimal("-0.20")
    if income_cents < HIGH_BAND_CENTS:
        return Decimal("0.00")
    return Decimal("0.15")


def _round_half_up(value):
    """Round a Decimal to whole cents, half up, returning an int."""
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def agency_fee_total(base_cents, income_cents, reimbursable_cents):
    """Compute (sliding_scale_pct_as_float, base_fee_cents, total_due_cents).

    base_fee_cents echoes the raw base at issuance. total_due_cents follows the
    pinned round-each-component-then-sum order.
    """
    pct = sliding_scale_pct(income_cents)
    # Step 2: cap the reimbursable pass-through.
    billable_reimbursable = min(reimbursable_cents, REIMBURSABLE_CAP_CENTS)
    # Step 3: apply the SAME scale to both components and round EACH separately.
    factor = Decimal(1) + pct
    adjusted_base = _round_half_up(Decimal(base_cents) * factor)
    adjusted_reimb = _round_half_up(Decimal(billable_reimbursable) * factor)
    # Step 4: total.
    total = adjusted_base + adjusted_reimb
    return float(pct), base_cents, total
