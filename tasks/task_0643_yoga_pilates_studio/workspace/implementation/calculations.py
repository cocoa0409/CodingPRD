"""Monetary calculations — Decimal with ROUND_HALF_UP (PRD §2.8, §3.7, §3.8)."""
from decimal import Decimal, ROUND_HALF_UP

import constants as C


def round_half_up(value):
    """Round a numeric/Decimal value half up to a whole integer (cents)."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def fee_amount_cents(fee_type, strikes_before_this, is_new_student):
    """fee_assessment (PRD §3.7).

    base depends on fee_type; surcharge tier keyed on strike count read BEFORE
    this event increments it; a still-new student pays 0.
    """
    if is_new_student:
        return 0
    base = C.NO_SHOW_BASE_CENTS if fee_type == "NO_SHOW" else C.LATE_CANCEL_BASE_CENTS
    if strikes_before_this >= C.REPEAT_OFFENDER_TIER2:
        surcharge = Decimal(base) * Decimal(str(C.SURCHARGE_TIER2_PCT))
    elif strikes_before_this >= C.REPEAT_OFFENDER_TIER1:
        surcharge = Decimal(base) * Decimal(str(C.SURCHARGE_TIER1_PCT))
    else:
        surcharge = Decimal(0)
    return round_half_up(Decimal(base) + surcharge)


def per_credit_cash_value(price_cents, credits_total):
    """final_cash_refund per credit (PRD §3.7).

    Finite pack: round_half_up(price_cents / credits_total).
    Unlimited membership (credits_total == -1) or non-positive total: 0.
    """
    if credits_total and credits_total > 0:
        return round_half_up(Decimal(price_cents) / Decimal(credits_total))
    return 0


def renewal_proration_total_cents(segments):
    """membership_renewal_proration (PRD §3.8).

    segments: list of {"segment_days": int, "monthly_rate_cents": int}
    Per-segment rounding, THEN integer sum. daily_rate = monthly/30.
    """
    total = 0
    for seg in segments:
        days = Decimal(seg["segment_days"])
        monthly = Decimal(seg["monthly_rate_cents"])
        daily_rate = monthly / Decimal(C.DAYS_PER_MONTH)
        seg_charge = round_half_up(days * daily_rate)
        total += seg_charge
    return total
