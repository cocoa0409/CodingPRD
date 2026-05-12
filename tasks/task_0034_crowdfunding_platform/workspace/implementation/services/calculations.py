"""Calculation rules per scaffold §1.3."""

from decimal import Decimal, ROUND_HALF_UP


COMMISSION_RATE_BPS = {
    "TECH": 500,
    "ART": 700,
    "COMMUNITY": 300,
}
CHANNEL_FEE_BPS = 290
CHANNEL_FEE_FLOOR_CENTS = 30
BACKUP_RATE_BPS = 2400
STANDARD_RATE_BPS = 1000
REPORTING_THRESHOLD_CENTS = 60000
MAX_SILENCE_DAYS = 30


def round_half_up(value) -> int:
    """Round half-up to the nearest integer cent."""
    if isinstance(value, int):
        return value
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    quantized = value.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(quantized)


def floor_int(value) -> int:
    if isinstance(value, int):
        return value
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    return int(value.to_integral_value(rounding="ROUND_FLOOR"))


def commission_for_order(order_total_cents: int, category: str) -> int:
    """Per-order commission rounded half-up."""
    rate = COMMISSION_RATE_BPS[category]
    raw = Decimal(order_total_cents) * Decimal(rate) / Decimal(10000)
    return round_half_up(raw)


def channel_fee_for_order(order_total_cents: int) -> int:
    """Per-order channel fee: max(floor(otc*BPS/10000), 30); then round_half_up.

    Since the raw value is already an integer (via floor) or 30, the round_half_up
    step is a no-op but we apply it for fidelity to the scaffold formula.
    """
    raw = Decimal(order_total_cents) * Decimal(CHANNEL_FEE_BPS) / Decimal(10000)
    floored = int(raw.to_integral_value(rounding="ROUND_FLOOR"))
    chosen = max(CHANNEL_FEE_FLOOR_CENTS, floored)
    return round_half_up(Decimal(chosen))


def commission_reversal(original_commission_cents: int, approved_amount_cents: int, order_total_cents: int) -> int:
    """Refund-induced commission reversal, proportional, round_half_up."""
    if order_total_cents <= 0:
        return 0
    raw = Decimal(original_commission_cents) * Decimal(approved_amount_cents) / Decimal(order_total_cents)
    return round_half_up(raw)


def tax_withholding(taxable_base_cents: int, tax_id) -> int:
    """Compute tax withheld per scaffold rule.

    - tax_id missing/empty: 24% backup withholding regardless of size.
    - tax_id present and taxable_base_cents > 60000: 10% standard.
    - tax_id present and taxable_base_cents <= 60000: 0.

    Negative or zero base => 0 withholding (defensive).
    """
    if taxable_base_cents <= 0:
        return 0
    if tax_id is None or (isinstance(tax_id, str) and tax_id.strip() == ""):
        raw = Decimal(taxable_base_cents) * Decimal(BACKUP_RATE_BPS) / Decimal(10000)
        return round_half_up(raw)
    if taxable_base_cents > REPORTING_THRESHOLD_CENTS:
        raw = Decimal(taxable_base_cents) * Decimal(STANDARD_RATE_BPS) / Decimal(10000)
        return round_half_up(raw)
    return 0
