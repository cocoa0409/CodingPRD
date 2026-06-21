"""Calculation rules (SCAFFOLD §1.3, PRD §3.5/§3.6/§3.7/§3.8).

All monetary math uses Decimal with ROUND_HALF_UP (PRD §2.6). Never float.
"""
from decimal import Decimal, ROUND_HALF_UP

SELF_PAY_DISCOUNT_FACTOR = Decimal("0.80")
NON_PARITY_PLAN_SHARE = Decimal("0.50")
DEA_EXAM_RECENCY_DAYS = 180
FOLLOW_UP_INTERVAL_DAYS = 30
VISIT_BUFFER_MINUTES = 30


def round_half_up(value):
    """Round a Decimal to the nearest whole cent, half rounds up. Returns int."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def patient_cost_insurance(list_fee_cents, payer):
    """INSURANCE variant (PRD §3.5).

    allowed = min(list_fee, payer.allowed_amount)
    parity:     cost = copay
    non-parity: cost = copay + max(0, list_fee - allowed)
    """
    allowed = min(list_fee_cents, payer["allowed_amount_cents"])
    copay = payer["copay_cents"]
    if payer["telehealth_parity"]:
        return copay
    parity_shortfall = max(0, list_fee_cents - allowed)
    return copay + parity_shortfall


def patient_cost_self_pay(list_fee_cents, platform_fee_cents):
    """SELF_PAY variant (PRD §3.5): per-component round-then-sum, factor 0.80."""
    clinical_share = round_half_up(Decimal(list_fee_cents) * SELF_PAY_DISCOUNT_FACTOR)
    platform_share = round_half_up(Decimal(platform_fee_cents) * SELF_PAY_DISCOUNT_FACTOR)
    return clinical_share + platform_share


def claim_adjudication(billed_cents, payer):
    """Compute (allowed_cents, plan_paid_cents) — PRD §3.6.

    allowed = min(billed, payer.allowed_amount)
    parity:     plan_paid = max(0, allowed - copay)
    non-parity: plan_paid = max(0, round_half_up(allowed * 0.50) - copay)
    """
    allowed = min(billed_cents, payer["allowed_amount_cents"])
    copay = payer["copay_cents"]
    if payer["telehealth_parity"]:
        plan_paid = max(0, allowed - copay)
    else:
        half = round_half_up(Decimal(allowed) * NON_PARITY_PLAN_SHARE)
        plan_paid = max(0, half - copay)
    return allowed, plan_paid
