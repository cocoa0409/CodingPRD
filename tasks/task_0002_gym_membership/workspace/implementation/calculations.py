"""Pure calculation functions. No side effects on data; callers persist results."""
from datetime import timedelta
from decimal import Decimal

from common import round_half_up_to_int, ceil_to_int, CLOCK
from constants import (
    PLAN_PRICE_CENTS, CLASS_BASE_PRICE_CENTS, TIER_PT_DISCOUNT_PCT,
    LATE_BOOKING_SURCHARGE_HOURS, LATE_BOOKING_SURCHARGE_PCT,
    NO_SHOW_PENALTY_CENTS, ADMIN_REFUND_PCT,
    refund_schedule, late_fee_pct,
)


def compute_account_posture(billing_status, access_status):
    """Derive account_posture (OPEN|RESTRICTED|FROZEN) from the two parallel axes."""
    if access_status in ("SUSPENDED", "FROZEN", "CANCELLED"):
        return "FROZEN"
    if billing_status in ("PAST_DUE", "GRACE", "DELINQUENT"):
        return "RESTRICTED"
    if billing_status in ("CURRENT", "REINSTATED") and access_status == "ACTIVE":
        return "OPEN"
    return "RESTRICTED"


def plan_base_price(plan, billing_cycle):
    cycle = PLAN_PRICE_CENTS.get(billing_cycle, {})
    return cycle.get(plan, 0)


def subscription_charge_amount(subscription, member, coupon):
    """
    Server-recompute the expected amount_cents for a payment attempt:
      gross = base_price_cents
      if coupon SUBSCRIPTION/BOTH:
        PERCENT_OFF  -> discount = round_half_up(gross * value/100)
        FIXED_OFF    -> discount = min(value, gross)
        else          -> 0
      net = gross - discount
      wallet_applied = min(wallet_credit_cents, net)
      amount = max(0, net - wallet_applied)
    """
    gross = subscription["base_price_cents"]
    discount = 0
    if coupon is not None and coupon["applicable_to"] in ("SUBSCRIPTION", "BOTH"):
        if coupon["kind"] == "PERCENT_OFF":
            discount = round_half_up_to_int(Decimal(gross) * Decimal(coupon["value"]) / Decimal(100))
        elif coupon["kind"] == "FIXED_OFF_CENTS":
            discount = min(coupon["value"], gross)
        elif coupon["kind"] == "REFERRAL_REWARD":
            # Same fixed-cents semantics as FIXED_OFF_CENTS
            discount = min(coupon["value"], gross)
    net = gross - discount
    wallet = max(0, member["wallet_credit_cents"])
    wallet_applied = min(wallet, net)
    amount = max(0, net - wallet_applied)
    return amount, wallet_applied, discount


def booking_provisional_price(*, booking_kind, class_session, trainer, member_tier,
                              starts_at, ends_at, coupon=None, now=None):
    """
    Calculate Booking.provisional_price_cents per the pinned formula:
      base = (group) CLASS_BASE_PRICE_CENTS[class_type]
             (PT) ceil(hourly_rate_cents * duration_minutes / 60)
      after_tier = base - round_half_up(base * tier_pct / 100)
      if hours_to_start < 2: surcharge = round_half_up(after_tier * 25 / 100) else 0
      subtotal = after_tier + surcharge
      coupon_disc = applied to subtotal (BOOKING/BOTH)
      result = max(0, subtotal - coupon_disc)
    """
    if now is None:
        now = CLOCK.now()

    if booking_kind == "GROUP_CLASS":
        base = CLASS_BASE_PRICE_CENTS.get(class_session["class_type"], 2000)
        # hours_to_start derived from class session
        sa = class_session["starts_at"]
    else:
        # PT: duration_minutes is floor of (ends - starts) in minutes
        delta = ends_at - starts_at
        duration_minutes = int(delta.total_seconds() // 60)
        if duration_minutes <= 0:
            duration_minutes = 0
        base = ceil_to_int(Decimal(trainer["hourly_rate_cents"]) * Decimal(duration_minutes) / Decimal(60))
        sa = starts_at

    tier_pct = TIER_PT_DISCOUNT_PCT.get(member_tier, 0)
    tier_disc = round_half_up_to_int(Decimal(base) * Decimal(tier_pct) / Decimal(100))
    after_tier = base - tier_disc

    hours_to_start = (sa - now).total_seconds() / 3600.0
    if hours_to_start < LATE_BOOKING_SURCHARGE_HOURS:
        surcharge = round_half_up_to_int(Decimal(after_tier) * Decimal(LATE_BOOKING_SURCHARGE_PCT) / Decimal(100))
    else:
        surcharge = 0

    subtotal = after_tier + surcharge

    coupon_disc = 0
    if coupon is not None and coupon["applicable_to"] in ("BOOKING", "BOTH"):
        if coupon["kind"] == "PERCENT_OFF":
            coupon_disc = round_half_up_to_int(Decimal(subtotal) * Decimal(coupon["value"]) / Decimal(100))
        elif coupon["kind"] == "FIXED_OFF_CENTS":
            coupon_disc = min(coupon["value"], subtotal)

    return max(0, subtotal - coupon_disc)


def booking_refund_pct_member(state_code, hours_to_start):
    """Walk the state's refund schedule (high threshold first); return refund_pct."""
    schedule = refund_schedule(state_code)
    for row in schedule:
        if hours_to_start >= row["hours_threshold"]:
            return row["refund_pct"]
    return 0


def compute_member_cancel_refund(state_code, provisional_price, hours_to_start):
    pct = booking_refund_pct_member(state_code, hours_to_start)
    refund = round_half_up_to_int(Decimal(provisional_price) * Decimal(pct) / Decimal(100))
    return refund, pct


def compute_admin_cancel_refund(provisional_price):
    """Admin/cascade cancel — 100% refund regardless of hours_to_start."""
    pct = ADMIN_REFUND_PCT
    refund = round_half_up_to_int(Decimal(provisional_price) * Decimal(pct) / Decimal(100))
    return refund, pct


def compute_late_payment_penalty(state_code, base_price_cents):
    pct = late_fee_pct(state_code)
    return round_half_up_to_int(Decimal(base_price_cents) * Decimal(pct) / Decimal(100))


def referral_reward_value(invitee_plan):
    from constants import REFERRAL_REWARD_CENTS_BY_PLAN
    return REFERRAL_REWARD_CENTS_BY_PLAN.get(invitee_plan, 1000)
