"""Calculation rules (scaffold §1.3 / PRD §2.9, §3.4, §3.5, §3.7, §3.8)."""
from decimal import Decimal

from util import round_half_up_cents, days_ceiling

PROCESSING_FEE_CENTS = 300
CALENDAR_DENOMINATOR_DAYS = 30

W_SHOULDER = Decimal("0.30")
W_HIP = Decimal("0.30")
W_SPINE = Decimal("0.25")
W_ANKLE = Decimal("0.15")

POINTS_NO_SHOW = 2
POINTS_LATE_CANCEL = 1
STRIKE_WINDOW_DAYS = 90
SUSPENSION_THRESHOLD = 5


def credit_pack_price(base_unit_price_cents, pack_credits):
    """calc credit_pack_price: discount -> round -> +flat fee (PRD §3.8)."""
    subtotal = Decimal(base_unit_price_cents) * Decimal(pack_credits)
    if pack_credits >= 20:
        discount_pct = Decimal("0.15")
    elif pack_credits >= 10:
        discount_pct = Decimal("0.10")
    elif pack_credits >= 5:
        discount_pct = Decimal("0.05")
    else:
        discount_pct = Decimal("0.00")
    discounted = subtotal * (Decimal("1") - discount_pct)
    discounted_cents = round_half_up_cents(discounted)  # round BEFORE fee
    return discounted_cents + PROCESSING_FEE_CENTS


def no_show_fee_late_cancel(list_price_cents, late_cancel_pct):
    """LATE_CANCEL variant: round_half_up(list_price_cents * late_cancel_pct)."""
    return round_half_up_cents(Decimal(list_price_cents) * Decimal(str(late_cancel_pct)))


def membership_freeze_proration(monthly_fee_cents, freeze_start_dt, freeze_end_dt):
    """calc membership_freeze_proration, PINNED variant CALENDAR_30 (PRD §3.7).

    frozen_days = ceil((end - start) to whole days)
    credit_cents = round_half_up(monthly_fee_cents * frozen_days / 30)
    """
    frozen_days = days_ceiling(freeze_start_dt, freeze_end_dt)
    value = (Decimal(monthly_fee_cents) * Decimal(frozen_days)) / Decimal(CALENDAR_DENOMINATOR_DAYS)
    return round_half_up_cents(value)


def intro_assessment_composite(shoulder, hip, spine, ankle):
    """calc intro_assessment_score: weighted sum in exact decimal, round once (PRD §3.4)."""
    total = (Decimal(shoulder) * W_SHOULDER
             + Decimal(hip) * W_HIP
             + Decimal(spine) * W_SPINE
             + Decimal(ankle) * W_ANKLE)
    composite = round_half_up_cents(total)  # round_half_up to integer, once
    if composite >= 80:
        tier = "ADVANCED"
    elif composite >= 60:
        tier = "INTERMEDIATE"
    else:
        tier = "FOUNDATION"
    return composite, tier
