"""Pinned calculations (PRD §2.7, §3.4-§3.9 and SCAFFOLD calculations)."""

import math
from decimal import Decimal

from util import add_days, add_months, rhu2, rhu_cents

# --------------------------------------------------------------------------- #
# constants
# --------------------------------------------------------------------------- #

INFORMALITY_LOADING_RATE = Decimal("0.0025")

AGGRAVATING_WEIGHTS = {
    "FRAUD": 40,
    "BID_RIGGING": 35,
    "FALSE_CERTIFICATION": 25,
    "REPEATED_NONPERFORMANCE": 20,
    "SAFETY_VIOLATION": 15,
    "ADMINISTRATIVE_DEFAULT": 5,
}
MITIGATING_WEIGHTS = {
    "SELF_DISCLOSURE": 15,
    "RESTITUTION_PAID": 12,
    "COMPLIANCE_PROGRAM": 10,
    "COOPERATION": 8,
}
MITIGATION_CAP_FRACTION = Decimal("0.5")
STRIKE_ESCALATION_POINTS = 10
INTERIM_THRESHOLD = Decimal("35")

HIGH_VALUE_THRESHOLD_CENTS = 500000000
WEIGHTS = {
    "STANDARD": (Decimal("0.3"), Decimal("0.4"), Decimal("0.3")),
    "HIGH_VALUE": (Decimal("0.5"), Decimal("0.3"), Decimal("0.2")),
}
STRIKE_PENALTY_PER_STRIKE = 7
STRIKE_PENALTY_CAP = 20
INTEGRITY_FLOOR = 40
INTEGRITY_FAILURE_CEILING = Decimal("49")
RESPONSIBLE_THRESHOLD = Decimal("60.00")

BASE_FEE_CENTS = 25000
GROUND_MULTIPLIERS = {
    "SOLICITATION_IMPROPRIETY": Decimal("0.1255"),
    "RESPONSIVENESS_DETERMINATION": Decimal("0.3335"),
    "RESPONSIBILITY_DETERMINATION": Decimal("0.2955"),
    "AWARD_IMPROPRIETY": Decimal("0.5015"),
    "EVALUATION_ERROR": Decimal("0.2135"),
}
PROTEST_RESERVE_RATE = Decimal("0.0050")

MAX_CUMULATIVE_EXTENSION_DAYS = 21
QUESTION_CUTOFF_DAYS = 7
STANDARD_WINDOW_DAYS = 7
AWARD_WINDOW_DAYS = 10
PRE_BID_MARGIN_DAYS = 1
MIN_SERVED_FRACTION = Decimal("0.5")
OFFICER_DAILY_MINUTE_CAP = 480
CHANGEOVER_BUFFER_MINUTES = 30
RESPONSE_WINDOW_DAYS = 14
MAX_CONTINUANCES = 2
LIVE_PROCEEDING_OCCUPANCY_DAYS = 3650


# --------------------------------------------------------------------------- #
# evaluated bid price
# --------------------------------------------------------------------------- #

def informality_loading(base_cents, unacked_count):
    """One ROUND_HALF_UP applied to base * rate * count, never per addendum."""
    if unacked_count <= 0:
        return 0
    return rhu_cents(Decimal(base_cents) * INFORMALITY_LOADING_RATE * Decimal(unacked_count))


# --------------------------------------------------------------------------- #
# debarment severity
# --------------------------------------------------------------------------- #

def aggravating_total(codes):
    return sum(AGGRAVATING_WEIGHTS[c] for c in set(codes))


def mitigating_raw(codes):
    return sum(MITIGATING_WEIGHTS[c] for c in set(codes))


def interim_severity(aggravating_codes):
    total = Decimal(aggravating_total(aggravating_codes))
    return rhu2(min(Decimal(100), total))


def final_severity(aggravating_codes, mitigating_codes, prior_strikes):
    agg = Decimal(aggravating_total(aggravating_codes))
    raw_mitigation = Decimal(mitigating_raw(mitigating_codes))
    credit = min(raw_mitigation, MITIGATION_CAP_FRACTION * agg)
    score = agg - credit + Decimal(STRIKE_ESCALATION_POINTS * prior_strikes)
    score = min(Decimal(100), max(Decimal(0), score))
    return rhu2(score), rhu2(credit), agg


def debarment_period_months(severity):
    if severity >= 80:
        return 60
    if severity >= 60:
        return 36
    if severity >= 40:
        return 24
    if severity >= 20:
        return 12
    return 0


# --------------------------------------------------------------------------- #
# responsibility composite score
# --------------------------------------------------------------------------- #

def weight_profile(estimated_value_cents):
    return "HIGH_VALUE" if estimated_value_cents >= HIGH_VALUE_THRESHOLD_CENTS else "STANDARD"


def composite_score(financial, performance, integrity, estimated_value_cents, strike_count):
    profile = weight_profile(estimated_value_cents)
    w_fin, w_perf, w_integ = WEIGHTS[profile]
    raw = Decimal(financial) * w_fin + Decimal(performance) * w_perf + Decimal(integrity) * w_integ
    penalty = min(STRIKE_PENALTY_CAP, STRIKE_PENALTY_PER_STRIKE * strike_count)
    capped = max(Decimal(0), min(Decimal(100), raw - Decimal(penalty)))
    if integrity < INTEGRITY_FLOOR:
        capped = min(capped, INTEGRITY_FAILURE_CEILING)
    return profile, penalty, rhu2(capped)


# --------------------------------------------------------------------------- #
# protest filing fee
# --------------------------------------------------------------------------- #

def filing_fee_cents(estimated_value_cents, grounds_code):
    c1 = rhu_cents(Decimal(BASE_FEE_CENTS))
    if estimated_value_cents <= 10000000:
        rate = Decimal("0.00075")
    elif estimated_value_cents <= 100000000:
        rate = Decimal("0.00050")
    else:
        rate = Decimal("0.00025")
    c2 = rhu_cents(Decimal(estimated_value_cents) * rate)
    c3 = rhu_cents(Decimal(BASE_FEE_CENTS) * GROUND_MULTIPLIERS[grounds_code])
    return c1 + c2 + c3


# --------------------------------------------------------------------------- #
# award obligation
# --------------------------------------------------------------------------- #

def administrative_fee_rate(base_obligation_cents):
    if base_obligation_cents <= 100000000:
        return Decimal("0.0150")
    if base_obligation_cents <= 500000000:
        return Decimal("0.0110")
    return Decimal("0.0075")


def award_amounts(base_obligation_cents, has_resolved_protest):
    rate = administrative_fee_rate(base_obligation_cents)
    fee = rhu_cents(Decimal(base_obligation_cents) * rate)
    if has_resolved_protest:
        reserve = rhu_cents(Decimal(base_obligation_cents + fee) * PROTEST_RESERVE_RATE)
    else:
        reserve = 0
    return rate, fee, reserve, base_obligation_cents + fee + reserve


# --------------------------------------------------------------------------- #
# temporal windows
# --------------------------------------------------------------------------- #

def question_deadline_from(effective_bid_due_utc):
    return add_days(effective_bid_due_utc, -QUESTION_CUTOFF_DAYS)


def response_deadline_from(notice_instant):
    return add_days(notice_instant, RESPONSE_WINDOW_DAYS)


def served_months_required(period_months):
    return int(math.ceil(float(Decimal(period_months) * MIN_SERVED_FRACTION)))


def earliest_petition_instant(debarment_start_utc, period_months):
    return add_months(debarment_start_utc, served_months_required(period_months))
