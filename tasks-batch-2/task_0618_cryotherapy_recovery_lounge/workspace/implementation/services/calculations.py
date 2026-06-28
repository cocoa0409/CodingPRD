"""Monetary calculation rules (PRD §3, scaffold §1.3).

All money is integer cents; rounding is round-half-up at the single pinned step
named in each function. No floating-point currency leaks out.
"""

import math
from decimal import Decimal, ROUND_HALF_UP

from helpers import round_half_up

# --- Constants (scaffold §1.3 + PRD §3) ---
BILLING_CYCLE_DAYS = 30

# Cancellation / no-show fee
FREE_CANCEL_MINUTES = 240
BASE_FEE_CENTS = 2000
LATE_RATE_PER_HOUR_CENTS = 1500
FEE_CAP_CENTS = 5000

# Credit-pack pricing
LIST_PRICE_PER_CREDIT_CENTS = 2195
INTRO_DISCOUNT_PCT = Decimal("0.30")
PLATFORM_FEE_PCT = Decimal("0.08")

# Freeze fee
FREEZE_FEE_CENTS = 1000

# Pack validity
PACK_VALIDITY_DAYS = 180


# ---------------------------------------------------------------------------
# Subscription cancellation refund (PRD §3.4, dual-variant).
# elapsed_days = floor((clock - cycle_anchor_at) / 1 day); remaining = 30 - elapsed.
# PROVISIONAL_REMAINING: round_half_up(fee * remaining / 30) — one rounding.
# FINAL_DAILY_FLOOR: daily = floor(fee / 30); refund = fee - daily * elapsed.
# ---------------------------------------------------------------------------

def provisional_remaining_cents(monthly_fee_cents, remaining_days):
    return round_half_up(
        Decimal(monthly_fee_cents) * Decimal(remaining_days) / Decimal(BILLING_CYCLE_DAYS)
    )


def final_daily_floor_cents(monthly_fee_cents, elapsed_days):
    daily_rate = monthly_fee_cents // BILLING_CYCLE_DAYS  # floor for non-negative ints
    return monthly_fee_cents - daily_rate * elapsed_days


# ---------------------------------------------------------------------------
# Credit-pack refund (PRD §3.6, dual-variant).
# per_credit_avg = round_half_up(price_paid_cents / total_credits).
# Non-intro (AVERAGE_PRICE_UNUSED): refund = per_credit_avg * remaining_credits.
# Intro (TOTAL_MINUS_CONSUMED): refund = price_paid_cents
#        - per_credit_avg * (total_credits - remaining_credits).
# ---------------------------------------------------------------------------

def credit_pack_refund_cents(pack):
    price_paid = pack["price_paid_cents"]
    total = pack["total_credits"]
    remaining = pack["remaining_credits"]
    per_credit_avg = round_half_up(Decimal(price_paid) / Decimal(total))
    if pack["is_intro"]:
        consumed = total - remaining
        return price_paid - per_credit_avg * consumed
    return per_credit_avg * remaining


# ---------------------------------------------------------------------------
# Cancellation / no-show fee (PRD §3.7).
# notice_minutes = floor((starts_at - clock) / 1 minute); NO_SHOW treats it as 0.
# Branches in order:
#   1) plan late_cancel_fee_waived -> 0
#   2) CANCEL mode and notice >= 240 -> 0
#   3) else hours_short = ceil((240 - notice) / 60); fee = min(cap, base + rate*hours_short)
# ---------------------------------------------------------------------------

def cancellation_fee_cents(mode, notice_minutes, late_cancel_fee_waived):
    if late_cancel_fee_waived:
        return 0
    if mode == "CANCEL" and notice_minutes >= FREE_CANCEL_MINUTES:
        return 0
    if mode == "NO_SHOW":
        notice_minutes = 0
    hours_short = math.ceil((FREE_CANCEL_MINUTES - notice_minutes) / 60)
    fee = BASE_FEE_CENTS + LATE_RATE_PER_HOUR_CENTS * hours_short
    return min(FEE_CAP_CENTS, fee)


# ---------------------------------------------------------------------------
# Credit-pack price (PRD §3.6, pinned rounding order).
# per_credit = round_half_up(2195 * (1 - discount));  round per line item
# subtotal   = per_credit * total_credits;             then sum
# price      = round_half_up(subtotal * (1 + 0.08));   then fee, round once
# ---------------------------------------------------------------------------

def credit_pack_price_cents(total_credits, is_intro):
    discount = INTRO_DISCOUNT_PCT if is_intro else Decimal("0")
    per_credit = round_half_up(
        Decimal(LIST_PRICE_PER_CREDIT_CENTS) * (Decimal("1") - discount)
    )
    subtotal = per_credit * total_credits
    price = round_half_up(Decimal(subtotal) * (Decimal("1") + PLATFORM_FEE_PCT))
    return price


# ---------------------------------------------------------------------------
# Subscription upgrade proration (PRD §3.4, pinned evaluation order).
# Computed from the CURRENT cycle anchor BEFORE re-anchoring.
# elapsed_days = floor((clock - cycle_anchor_at) / 1 day); remaining = 30 - elapsed.
# fee_delta = new_fee - old_fee (> 0).
# proration = round_half_up(fee_delta * remaining_days / 30).
# ---------------------------------------------------------------------------

def upgrade_proration_cents(fee_delta, remaining_days):
    return round_half_up(
        Decimal(fee_delta) * Decimal(remaining_days) / Decimal(BILLING_CYCLE_DAYS)
    )
