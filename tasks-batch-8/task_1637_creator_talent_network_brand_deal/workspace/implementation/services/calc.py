"""Calculation rules from the scaffold `calculations` table. All money is
integer cents; rounding is round-half-up per step unless a rule pins
otherwise (the performance-bonus engagement rate rounds half down)."""

import math
from decimal import Decimal, ROUND_HALF_UP, ROUND_HALF_DOWN

# rate_card_computation constants
NANO_BASE_CPM = 1500
MICRO_BASE_CPM = 2200
MID_BASE_CPM = 3000
MACRO_BASE_CPM = 4500
MIN_FLAT_FEE_CENTS = 50000

# deal_fee_computation constants
MULTI_DELIVERABLE_DISCOUNT = Decimal("0.10")
WHITELIST_PER_DELIVERABLE_CENTS = 75000
EXCL_TIER1_MAX = 500000
EXCL_TIER2_MAX = 2000000

# invoice_total_computation constants
SERVICE_FEE_PCT = Decimal("0.05")

# performance_bonus constants
BONUS_T1_VIEWS = 250000
BONUS_T1_CENTS = 25000
BONUS_T2_VIEWS = 1000000
BONUS_T2_CENTS = 100000
BONUS_T3_VIEWS = 5000000
BONUS_T3_CENTS = 400000
BONUS_ENG_KICKER_BPS = 400

# commission_split constants
COMMISSION_T1_MAX = 5000000
COMMISSION_T2_MAX = 20000000

# late_fee_accrual constants
LATE_FEE_PCT = Decimal("0.015")
LATE_FEE_PERIOD_DAYS = 7


def _round_half_up(value: Decimal) -> int:
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def rate_card(followers: int, engagement_rate_bps: int, niche: str,
              avg_views_30d: int):
    """rate_card_computation -> (rate_card_cpm_cents, rate_card_flat_cents)."""
    if followers < 10000:
        base_cpm = NANO_BASE_CPM
    elif followers < 100000:
        base_cpm = MICRO_BASE_CPM
    elif followers < 1000000:
        base_cpm = MID_BASE_CPM
    else:
        base_cpm = MACRO_BASE_CPM

    if engagement_rate_bps < 100:
        eng_mult = Decimal("0.80")
    elif engagement_rate_bps < 300:
        eng_mult = Decimal("1.00")
    elif engagement_rate_bps < 600:
        eng_mult = Decimal("1.15")
    else:
        eng_mult = Decimal("1.30")

    if niche in ("FINANCE", "TECH"):
        niche_mult = Decimal("1.20")
    elif niche in ("BEAUTY", "FASHION"):
        niche_mult = Decimal("1.10")
    else:
        niche_mult = Decimal("1.00")

    cpm = _round_half_up(Decimal(base_cpm) * eng_mult * niche_mult)
    flat = _round_half_up(Decimal(cpm) * Decimal(avg_views_30d) / Decimal(1000))
    flat = max(MIN_FLAT_FEE_CENTS, flat)
    return cpm, flat


def deal_fee(rate_card_flat_cents: int, deliverables_per_slot: int,
             usage_rights_days: int, whitelisting: bool,
             exclusivity_category: str) -> int:
    """deal_fee_computation — pinned evaluation order, round per step."""
    base_sum = rate_card_flat_cents * deliverables_per_slot
    if deliverables_per_slot >= 3:
        base_after_discount = _round_half_up(
            Decimal(base_sum) * (Decimal(1) - MULTI_DELIVERABLE_DISCOUNT))
    else:
        base_after_discount = base_sum

    if usage_rights_days <= 30:
        usage_pct = Decimal("0.00")
    elif usage_rights_days <= 90:
        usage_pct = Decimal("0.10")
    elif usage_rights_days <= 365:
        usage_pct = Decimal("0.25")
    else:
        usage_pct = Decimal("0.50")
    usage_addon = _round_half_up(Decimal(base_after_discount) * usage_pct)

    whitelist_addon = (WHITELIST_PER_DELIVERABLE_CENTS * deliverables_per_slot
                       if whitelisting else 0)

    subtotal = base_after_discount + usage_addon + whitelist_addon

    if exclusivity_category == "NONE":
        uplift_pct = Decimal("0")
    elif subtotal < EXCL_TIER1_MAX:
        uplift_pct = Decimal("0.05")
    elif subtotal < EXCL_TIER2_MAX:
        uplift_pct = Decimal("0.12")
    else:
        uplift_pct = Decimal("0.20")

    return _round_half_up(Decimal(subtotal) * (Decimal(1) + uplift_pct))


def invoice_lines(fee_total_cents: int, reduction_pct, bonus_accrued_cents: int):
    """invoice_total_computation — round each line first, then sum."""
    reduction = Decimal(str(reduction_pct or 0))
    fee_line = _round_half_up(Decimal(fee_total_cents) * (Decimal(1) - reduction))
    service_line = _round_half_up(
        SERVICE_FEE_PCT * Decimal(fee_total_cents) * (Decimal(1) - reduction))
    bonus_line = int(bonus_accrued_cents or 0)
    total = fee_line + service_line + bonus_line
    return fee_line, service_line, bonus_line, total


def performance_bonus(views: int, engagements: int) -> int:
    """performance_bonus — highest qualifying tier, then 1.25x engagement
    kicker when engagement rate >= 400 bps (rate rounds half down)."""
    if views >= BONUS_T3_VIEWS:
        tier_bonus = BONUS_T3_CENTS
    elif views >= BONUS_T2_VIEWS:
        tier_bonus = BONUS_T2_CENTS
    elif views >= BONUS_T1_VIEWS:
        tier_bonus = BONUS_T1_CENTS
    else:
        tier_bonus = 0

    if views == 0:
        engagement_rate_bps = 0
    else:
        engagement_rate_bps = int(
            (Decimal(engagements) * Decimal(10000) / Decimal(views)).quantize(
                Decimal("1"), rounding=ROUND_HALF_DOWN))

    if engagement_rate_bps >= BONUS_ENG_KICKER_BPS:
        return _round_half_up(Decimal(tier_bonus) * Decimal("1.25"))
    return tier_bonus


def commission(lifetime_billed_cents: int, gross_cents: int):
    """commission_split -> (rate_bps, commission_cents, net_cents)."""
    if lifetime_billed_cents < COMMISSION_T1_MAX:
        rate_bps = 2000
    elif lifetime_billed_cents < COMMISSION_T2_MAX:
        rate_bps = 1500
    else:
        rate_bps = 1200
    commission_cents = _round_half_up(
        Decimal(gross_cents) * Decimal(rate_bps) / Decimal(10000))
    net_cents = gross_cents - commission_cents
    return rate_bps, commission_cents, net_cents


def late_fee(payment_instant, due_date, total_cents: int) -> int:
    """late_fee_accrual — whole days overdue (ceil), 7-day started periods
    (ceil), 1.5% of total per period, round half up. Zero when payment is not
    after due_date."""
    seconds = (payment_instant - due_date).total_seconds()
    if seconds <= 0:
        return 0
    days_overdue = math.ceil(seconds / 86400)
    started_periods = math.ceil(days_overdue / LATE_FEE_PERIOD_DAYS)
    return _round_half_up(
        Decimal(total_cents) * LATE_FEE_PCT * Decimal(started_periods))
