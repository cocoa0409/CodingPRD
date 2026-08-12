"""The fourteen calculations of the scaffold, five of them dual-variant."""

from datetime import date, time, timedelta
from decimal import Decimal, ROUND_HALF_UP

from . import constants as K
from .clock import (
    add_business_days,
    days_in_month,
    parse_date,
    parse_month,
    render_date,
    roll_to_business_day,
)


def round_half_up(value):
    """Round-half-up to a whole cent; exactly on the half rounds away from 0."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# -- payment_total_charge -------------------------------------------------

def service_fee_cents(amount_cents):
    """Band selected from the pre-fee principal ALONE; never re-selected."""
    if amount_cents < K.SERVICE_FEE_TIER1_UPPER_EXCLUSIVE_CENTS:
        return K.SERVICE_FEE_TIER1_CENTS
    if amount_cents < K.SERVICE_FEE_TIER2_UPPER_EXCLUSIVE_CENTS:
        return K.SERVICE_FEE_TIER2_CENTS
    return K.SERVICE_FEE_TIER3_CENTS


def total_charge_cents(amount_cents):
    return amount_cents + service_fee_cents(amount_cents)


# -- payment_settlement_schedule -----------------------------------------

def settlement_date(evaluation_instant, requested_send_date, channel):
    """Three ordered stages: cut-off, weekend roll, business-day lead."""
    start = parse_date(requested_send_date) if requested_send_date else None
    if start is None:
        start = evaluation_instant.date()
    d = start
    # Stage one - the cut-off, inclusive on the late side.
    if d == evaluation_instant.date() and evaluation_instant.time() >= time(
        *K.SAME_DAY_CUTOFF_UTC
    ):
        d = d + timedelta(days=1)
    # Stage two - the weekend roll, forward only.
    d = roll_to_business_day(d)
    # Stage three - the business-day lead; the submit date is day zero.
    d = add_business_days(d, K.CHANNEL_LEAD_DAYS.get(channel, 0))
    return render_date(d)


# -- budget_variance ------------------------------------------------------

def prorated_allocation_cents(allocation_cents, override_granted_cents,
                              budget_month, current_date):
    parsed = parse_month(budget_month)
    if parsed is None:
        return allocation_cents + override_granted_cents
    year, month = parsed
    total_days = days_in_month(year, month)
    budget_ord = year * 12 + month
    current_ord = current_date.year * 12 + current_date.month
    if current_ord < budget_ord:
        elapsed = 0
    elif current_ord > budget_ord:
        elapsed = total_days
    else:
        elapsed = min(total_days, max(0, current_date.day))
    base = Decimal(allocation_cents + override_granted_cents) * Decimal(elapsed)
    return round_half_up(base / Decimal(total_days))


def variance_direction(variance_ptd_cents):
    if variance_ptd_cents > 0:
        return "UNDER"
    if variance_ptd_cents == 0:
        return "EXACT"
    return "OVER"


# -- fraud_risk_band ------------------------------------------------------

def fraud_score(payment, payee):
    amount = payment["amount_cents"]
    if amount >= K.FRAUD_AMOUNT_HIGH_CENTS:
        amount_points = K.FRAUD_AMOUNT_POINTS_HIGH
    elif amount >= K.FRAUD_AMOUNT_MID_CENTS:
        amount_points = K.FRAUD_AMOUNT_POINTS_MID
    else:
        amount_points = K.FRAUD_AMOUNT_POINTS_LOW

    settled = payee["settled_payment_count"]
    if settled == 0:
        novelty_points = K.FRAUD_NOVELTY_POINTS_NEVER_PAID
    elif settled <= K.FRAUD_NOVELTY_SETTLED_COUNT_THIN_MAX:
        novelty_points = K.FRAUD_NOVELTY_POINTS_THIN
    else:
        novelty_points = K.FRAUD_NOVELTY_POINTS_ESTABLISHED

    channel = payment["channel"]
    if channel == "CHECK":
        channel_points = K.FRAUD_CHANNEL_POINTS_CHECK
    elif channel == "ACH":
        channel_points = K.FRAUD_CHANNEL_POINTS_ACH
    else:
        channel_points = K.FRAUD_CHANNEL_POINTS_BILLER_DIRECT

    return amount_points + novelty_points + channel_points


def fraud_band(score):
    if score >= K.FRAUD_BAND_HIGH_MIN_SCORE:
        return "HIGH"
    if score >= K.FRAUD_BAND_MEDIUM_MIN_SCORE:
        return "MEDIUM"
    return "LOW"


def fraud_ack_sla_hours(band):
    if band == "HIGH":
        return K.FRAUD_ACK_SLA_HOURS_HIGH
    if band == "MEDIUM":
        return K.FRAUD_ACK_SLA_HOURS_MEDIUM
    return K.FRAUD_ACK_SLA_HOURS_LOW


# -- benefit_countable_resources -----------------------------------------

def _countable_item(item):
    item_type = item.get("item_type")
    value = item.get("value_cents", 0)
    if item_type in ("HOME", "VEHICLE"):
        return 0
    if item_type == "BURIAL_FUND":
        return max(0, value - K.BURIAL_EXCLUSION_CAP_CENTS)
    if item_type == "RETIREMENT":
        return round_half_up(Decimal(value) * Decimal(K.RETIREMENT_COUNTABLE_RATE))
    if item_type == "LIFE_INSURANCE":
        return round_half_up(Decimal(value) * Decimal(K.LIFE_INSURANCE_COUNTABLE_RATE))
    if item_type == "CASH":
        return value
    return 0


def countable_resources(resource_items):
    """Round per item, then sum - never sum then round."""
    gross = 0
    net = 0
    for item in resource_items:
        gross += item.get("value_cents", 0)
        net += _countable_item(item)
    return gross, net


# -- retroactive_award_posting -------------------------------------------

def retro_months(decision_date, award_effective_date):
    d = parse_date(decision_date)
    a = parse_date(award_effective_date)
    if d is None or a is None:
        return 0
    return (d.year * 12 + d.month) - (a.year * 12 + a.month)


# -- authorization_scope_matrix ------------------------------------------

def scope_permits_payment(scope_tier, payee_type):
    if scope_tier == "FULL_AGENCY":
        return True
    if scope_tier == "LIMITED_BILLPAY":
        return payee_type == "RECURRING_BILLER"
    if scope_tier == "REP_PAYEE":
        return payee_type in ("RECURRING_BILLER", "ESSENTIAL")
    return False


def scope_permits_benefit_application(scope_tier):
    return scope_tier in ("FULL_AGENCY", "REP_PAYEE")


def scope_permits_family_recipient(scope_tier):
    return scope_tier in ("FULL_AGENCY", "REP_PAYEE")


def scope_amount_ceiling(scope_tier):
    if scope_tier == "LIMITED_BILLPAY":
        return K.LIMITED_SCOPE_MAX_PAYMENT_CENTS
    if scope_tier == "REP_PAYEE":
        return K.REP_PAYEE_MAX_PAYMENT_CENTS
    return None


# -- calendar-day helpers -------------------------------------------------

def days_between(a_str, b_str):
    """Whole calendar days from a to b; None when either is unparseable."""
    a = parse_date(a_str)
    b = parse_date(b_str)
    if a is None or b is None:
        return None
    return (b - a).days
