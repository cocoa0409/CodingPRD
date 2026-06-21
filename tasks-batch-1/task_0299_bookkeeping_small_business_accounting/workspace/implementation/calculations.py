"""Calculation rules (SCAFFOLD §1.3, PRD §2.8 / §3.6 / §3.8).

All money is integer cents. Tax/discount rounding is ROUND HALF UP, applied
per line then summed (PRD §2.8). decimal.Decimal is used for precision-sensitive
steps; never float.
"""
from decimal import Decimal, ROUND_HALF_UP

BPS_DENOMINATOR = 10000

# Invoice volume-discount tiers (SCAFFOLD §1.3 invoice_total_breakdown).
TIER1_THRESHOLD_CENTS = 500000   # >= $5,000 -> 5%
TIER2_THRESHOLD_CENTS = 1000000  # >= $10,000 -> 10%
TIER1_PCT = Decimal("0.05")
TIER2_PCT = Decimal("0.10")


def round_half_up(value):
    """Round a Decimal to the nearest whole cent, half up. Returns int."""
    if not isinstance(value, Decimal):
        value = Decimal(value)
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def invoice_total_breakdown(lines, applied_tax_rate_bps):
    """Pinned order: subtotals -> discount -> tax -> total (PRD §3.6).

    lines: list of {description, quantity, unit_price_cents, taxable}.
    Returns dict with taxable_subtotal_cents, nontaxable_subtotal_cents,
    discount_cents, tax_cents, total_cents.
    """
    taxable_lines = []
    taxable_subtotal = 0
    nontaxable_subtotal = 0
    for ln in lines:
        amount = int(ln["quantity"]) * int(ln["unit_price_cents"])
        if ln.get("taxable"):
            taxable_subtotal += amount
            taxable_lines.append(amount)
        else:
            nontaxable_subtotal += amount

    # 1) discount tier keyed on taxable_subtotal_cents
    if taxable_subtotal >= TIER2_THRESHOLD_CENTS:
        discount_pct = TIER2_PCT
    elif taxable_subtotal >= TIER1_THRESHOLD_CENTS:
        discount_pct = TIER1_PCT
    else:
        discount_pct = Decimal("0")
    discount_cents = round_half_up(Decimal(taxable_subtotal) * discount_pct)

    # 2) tax on the discounted taxable base, per-line round then sum
    discounted_taxable = taxable_subtotal - discount_cents
    tax_cents = 0
    if taxable_subtotal > 0:
        ratio = Decimal(discounted_taxable) / Decimal(taxable_subtotal)
        for line_amount in taxable_lines:
            line_share = (
                Decimal(line_amount)
                * Decimal(applied_tax_rate_bps)
                / Decimal(BPS_DENOMINATOR)
                * ratio
            )
            tax_cents += round_half_up(line_share)

    # 3) total last
    total_cents = discounted_taxable + nontaxable_subtotal + tax_cents

    return {
        "taxable_subtotal_cents": taxable_subtotal,
        "nontaxable_subtotal_cents": nontaxable_subtotal,
        "discount_cents": discount_cents,
        "tax_cents": tax_cents,
        "total_cents": total_cents,
    }


def bill_use_tax_total(lines, applied_tax_rate_bps):
    """subtotal = sum amount_cents; use tax per use_taxable line round-half-up
    then sum; total = subtotal + use_tax (SCAFFOLD §1.3 bill_use_tax_total)."""
    subtotal = 0
    use_tax = 0
    for ln in lines:
        amount = int(ln["amount_cents"])
        subtotal += amount
        if ln.get("use_taxable"):
            line_tax = (
                Decimal(amount)
                * Decimal(applied_tax_rate_bps)
                / Decimal(BPS_DENOMINATOR)
            )
            use_tax += round_half_up(line_tax)
    return {
        "subtotal_cents": subtotal,
        "use_tax_cents": use_tax,
        "total_cents": subtotal + use_tax,
    }
