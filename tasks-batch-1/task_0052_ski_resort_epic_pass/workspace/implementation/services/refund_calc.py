"""End-of-season refund payout calculation (PRD §3.5 / §2.7)."""
from decimal import Decimal, ROUND_HALF_UP

MAX_SCANS_FOR_REFUND = 10
PROCESSING_FEE_RATE = Decimal("0.10")


def _round_half_up(value):
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def compute_refund(basis_cents, used_count, reason):
    """Return integer-cents payout. Rounding applied exactly once to final value."""
    basis = Decimal(basis_cents)
    if reason == "INJURY":
        # Flat 90% of basis, ignoring usage entirely.
        return _round_half_up(basis * Decimal("0.90"))

    # RELOCATION / DISSATISFIED: prorate by unused share, then 10% processing fee,
    # with a single rounding step on the final cents value.
    if used_count >= MAX_SCANS_FOR_REFUND:
        return 0
    unused_fraction = Decimal(MAX_SCANS_FOR_REFUND - used_count) / Decimal(MAX_SCANS_FOR_REFUND)
    raw = basis * unused_fraction * (Decimal(1) - PROCESSING_FEE_RATE)
    return _round_half_up(raw)
