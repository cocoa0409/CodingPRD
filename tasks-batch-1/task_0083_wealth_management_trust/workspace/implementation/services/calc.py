"""Calculation rules (SCAFFOLD §1.3, PRD §3.4, §3.6, §3.9)."""
from decimal import Decimal, ROUND_HALF_UP

# Trust income tax compressed brackets (cents) and rates.
B1 = 310000
B2 = 1115000
B3 = 1520000
R1 = Decimal("0.10")
R2 = Decimal("0.24")
R3 = Decimal("0.35")
R4 = Decimal("0.37")

GST_RATE = Decimal("0.40")


def round_half_up(value):
    """Round a Decimal to the nearest whole cent, half up. Returns int."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def receipt_ledger_side(receipt_kind, capital_gains_to_income):
    """principal_income_allocation for a Receipt (PRD §3.3)."""
    if receipt_kind == "CONTRIBUTION":
        return "PRINCIPAL"
    if receipt_kind == "CAPITAL_GAIN":
        return "INCOME" if capital_gains_to_income else "PRINCIPAL"
    # INTEREST, DIVIDEND_ORDINARY, DIVIDEND_QUALIFIED
    return "INCOME"


def disbursement_ledger_side(expense_kind):
    """principal_income_allocation for a Disbursement (PRD §3.3)."""
    if expense_kind in ("INVESTMENT_FEE", "TAX_PAYMENT"):
        return "PRINCIPAL"
    # TRUSTEE_FEE, ADMINISTRATIVE
    return "INCOME"


def trust_income_tax(taxable_income_snapshot_cents, is_grantor_trust):
    """trust_income_tax (PRD §3.9). Marginal four-bracket schedule."""
    if is_grantor_trust:
        return 0
    ti = taxable_income_snapshot_cents
    tax = Decimal(0)
    tax += Decimal(min(ti, B1)) * R1
    if ti > B1:
        tax += Decimal(min(ti, B2) - B1) * R2
    if ti > B2:
        tax += Decimal(min(ti, B3) - B2) * R3
    if ti > B3:
        tax += Decimal(ti - B3) * R4
    return round_half_up(tax)


def gst_tax(taxable_amount_cents, inclusion_ratio_snapshot):
    """gst_tax (PRD §3.9). amount * inclusion_ratio * 0.40, round half up."""
    value = Decimal(taxable_amount_cents) * Decimal(str(inclusion_ratio_snapshot)) * GST_RATE
    return round_half_up(value)


def inclusion_ratio(gst_exemption_allocated_cents, principal_balance_cents):
    """1 - allocated/principal, 6 dp, clamped [0,1]; 0 when principal == 0 (PRD §3.8)."""
    if principal_balance_cents == 0:
        return 0.0
    ratio = Decimal(1) - (Decimal(gst_exemption_allocated_cents) / Decimal(principal_balance_cents))
    ratio = ratio.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)
    if ratio < 0:
        ratio = Decimal(0)
    elif ratio > 1:
        ratio = Decimal(1)
    return float(ratio)
