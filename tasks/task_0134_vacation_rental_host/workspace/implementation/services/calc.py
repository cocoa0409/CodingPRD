"""Calculation rules (SCAFFOLD §1.3, PRD §3). Money in integer cents, round_half_up."""
from datetime import timedelta
from decimal import Decimal

from errors import err
from util import round_half_up, round_half_up_2dp, date_only

BPS = Decimal(10000)
WEEKEND_WEEKDAYS = {4, 5}  # Monday=0 ... Friday=4, Saturday=5

CANCEL_WEIGHT = 15
CHARGEBACK_WEIGHT = 60
UNVERIFIED_WEIGHT = 40
RISK_THRESHOLD = 50  # PASS only if risk_score strictly < 50


def _rate_plan_for_date(rate_plans, d):
    """Return the single RatePlan whose closed [window_start, window_end] contains d,
    or None. If two plans contain d, raise ERR_RATE_PLAN_OVERLAP (PRD §3.4)."""
    matches = []
    for rp in rate_plans:
        ws = date_only(rp["window_start"])
        we = date_only(rp["window_end"])
        if ws <= d <= we:  # closed interval, inclusive both ends
            matches.append(rp)
    if len(matches) > 1:
        raise err("ERR_RATE_PLAN_OVERLAP", "multiple rate plans match a stay date")
    return matches[0] if matches else None


def nightly_pricing(listing, rate_plans, check_in_dt, check_out_dt):
    """Walk each night in [check_in, check_out) (half-open; checkout night excluded).
    Per-night price = round_half_up(base * sm/10000 * wm/10000), summed (SCAFFOLD
    nightly_pricing / PRD §3.4). Each night rounded individually before summing."""
    base = Decimal(listing["base_nightly_rate_cents"])
    subtotal = 0
    d = date_only(check_in_dt)
    end = date_only(check_out_dt)
    while d < end:
        plan = _rate_plan_for_date(rate_plans, d)
        if plan is None:
            sm = BPS
            wm = BPS
        else:
            sm = Decimal(plan["seasonal_multiplier_bps"])
            is_weekend = d.weekday() in WEEKEND_WEEKDAYS
            wm = Decimal(plan["weekend_multiplier_bps"]) if is_weekend else BPS
        night_price = round_half_up(base * sm / BPS * wm / BPS)
        subtotal += night_price
        d = d + timedelta(days=1)
    return subtotal


def booking_total(listing, nightly_subtotal_cents, pets_count):
    """fees + tax + total (SCAFFOLD booking_total / PRD §3.4). Tax rounded once,
    round_half_up, after summing the taxable base."""
    fees = listing["cleaning_fee_cents"]
    if pets_count > 0:
        fees += listing["pet_fee_cents"]
    taxable_base = nightly_subtotal_cents + fees
    tax = round_half_up(Decimal(taxable_base) * Decimal(listing["tax_rate_bps"]) / BPS)
    total = nightly_subtotal_cents + fees + tax
    return fees, tax, total


def refund_pct(tier, lead_hours):
    """Refund percentage by tier + lead time (PRD §3.9, SCAFFOLD cancellation_refund).
    All thresholds inclusive at the boundary (>=)."""
    if tier == "FLEXIBLE":
        return 100 if lead_hours >= 24 else 0
    if tier == "MODERATE":
        if lead_hours >= 120:
            return 100
        if lead_hours >= 24:
            return 50
        return 0
    if tier == "STRICT":
        return 50 if lead_hours >= 168 else 0
    return 0


def lead_hours_for(booking, current_utc):
    """Whole hours between current instant and check_in, floored at 0 (PRD §3.9)."""
    delta = booking["check_in"] - current_utc
    secs = delta.total_seconds()
    if secs <= 0:
        return 0
    return int(secs // 3600)


def cancellation_refund(booking, current_utc):
    """FINAL/PROVISIONAL refund. Refundable base = nightly_subtotal + tax.
    Returns (refund_cents, applied_pct, lead_hours)."""
    refundable_base = booking["nightly_subtotal_cents"] + booking["tax_cents"]
    tier = booking["cancellation_tier_snapshot"]
    lead = lead_hours_for(booking, current_utc)
    pct = refund_pct(tier, lead)
    refund = round_half_up(Decimal(refundable_base) * Decimal(pct) / Decimal(100))
    return refund, pct, lead


def payout_gross_and_commission(listing, booking):
    """Host gross (nightly_subtotal + fees; tax excluded) and round_half_up commission
    (SCAFFOLD payout_amount / PRD §3.6, §3.8)."""
    gross = booking["nightly_subtotal_cents"] + booking["fees_cents"]
    commission = round_half_up(
        Decimal(gross) * Decimal(listing["platform_commission_bps"]) / BPS
    )
    return gross, commission


def payout_estimate(listing, booking):
    gross, commission = payout_gross_and_commission(listing, booking)
    return gross - commission


def payout_actual(listing, booking, approved_deductions):
    """ACTUAL = max(0, gross - commission - sum(approved DamageClaim amounts))."""
    gross, commission = payout_gross_and_commission(listing, booking)
    return max(0, gross - commission - approved_deductions)


def guest_risk_score(guest):
    """Weighted screening score capped at 100, round_half_up to 2dp (PRD §3.5)."""
    score = 0
    score += guest["prior_cancellations"] * CANCEL_WEIGHT
    score += CHARGEBACK_WEIGHT if guest["chargeback_flag"] else 0
    score += 0 if guest["govt_id_verified"] else UNVERIFIED_WEIGHT
    score = min(100, score)
    return round_half_up_2dp(Decimal(score))


def screening_outcome(guest, risk_score):
    """Resolve PASSED/FAILED + dominant failure_reason (PRD §3.5).
    Precedence: ID_UNVERIFIED > CHARGEBACK > RISK_THRESHOLD."""
    passed = (
        guest["govt_id_verified"] is True
        and guest["chargeback_flag"] is False
        and risk_score < RISK_THRESHOLD
    )
    if passed:
        return "PASSED", "NONE"
    if not guest["govt_id_verified"]:
        return "FAILED", "ID_UNVERIFIED"
    if guest["chargeback_flag"]:
        return "FAILED", "CHARGEBACK"
    return "FAILED", "RISK_THRESHOLD"
