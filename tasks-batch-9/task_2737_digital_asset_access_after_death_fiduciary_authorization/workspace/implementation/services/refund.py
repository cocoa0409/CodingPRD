"""Subscription refund entitlement (PRD section 3.7 / calculation 7)."""
from money import round_half_up

DAYS_PER_WHOLE_MONTH = 30
REFUND_MIN_CLAIM_DAYS = 7


def entitlement(method, period_fee_cents, term_days, claimed_days):
    if method == "PRORATA_DAILY":
        return round_half_up(period_fee_cents * claimed_days, term_days)
    if method == "UNUSED_PERIOD":
        whole_months = claimed_days // DAYS_PER_WHOLE_MONTH
        billable_days = whole_months * DAYS_PER_WHOLE_MONTH
        return round_half_up(period_fee_cents * billable_days, term_days)
    return 0
